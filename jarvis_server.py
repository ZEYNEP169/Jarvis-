from flask import Flask, request, jsonify, render_template_string, session, redirect
from flask_socketio import SocketIO
from pycloudflared import try_cloudflare   
import qrcode
import io
import base64
import threading
import os
import requests
from datetime import datetime

# ══════════════════════════════════════════
#  YAMA_UYGULANDI_v1: PIN ile giris, oturum, hatali deneme siniri
# ══════════════════════════════════════════
import time
import hmac
import secrets
from datetime import timedelta

def _gizli_oku(env_adi, dosya):
    """Gizli degeri once ortam degiskeninden, yoksa dosyadan okur (kodun icinde durmaz, GitHub'a gitmez)."""
    v = os.environ.get(env_adi, "").strip()
    if v:
        return v
    try:
        with open(dosya, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        print("UYARI: %s ortam degiskeni ya da %s dosyasi bulunamadi." % (env_adi, dosya))
        return ""


NGROK_DOMAIN = _gizli_oku("JARVIS_NGROK_DOMAIN", r"C:\Jarvis\ngrok_domain.txt")
ALLOWED_ORIGINS = [
    f"https://{NGROK_DOMAIN}",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]

PIN_FILE = r"C:\Jarvis\jarvis_pin.txt"
SECRET_FILE = r"C:\Jarvis\flask_secret.key"

MAX_FAILS_PER_IP = 5      # ayni IP'den 5 hatali PIN -> 5 dk kilit
MAX_FAILS_GLOBAL = 20     # toplam 20 hatali PIN -> 15 dk herkese kilit
IP_WINDOW = 300
GLOBAL_WINDOW = 900

_fail_lock = threading.Lock()
_fails = {}
_global_fails = []


def _load_pin():
    pin = os.environ.get("JARVIS_PIN", "").strip()
    if pin:
        return pin
    try:
        with open(PIN_FILE, "r", encoding="utf-8") as f:
            pin = f.read().strip()
        if pin:
            return pin
    except Exception:
        pass
    pin = "".join(secrets.choice("0123456789") for _ in range(8))
    try:
        os.makedirs(os.path.dirname(PIN_FILE), exist_ok=True)
        with open(PIN_FILE, "w", encoding="utf-8") as f:
            f.write(pin)
    except Exception as e:
        print("PIN dosyasi yazilamadi:", e)
    print(f"[GUVENLIK] Web arayuzu PIN'i olusturuldu: {pin}   (dosya: {PIN_FILE})")
    return pin


def _load_secret():
    try:
        with open(SECRET_FILE, "r", encoding="utf-8") as f:
            s = f.read().strip()
        if len(s) >= 32:
            return s
    except Exception:
        pass
    s = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(s)
    except Exception as e:
        print("Gizli anahtar dosyasi yazilamadi:", e)
    return s


JARVIS_PIN = _load_pin()


def client_ip():
    # ngrok gercek IP'yi X-Forwarded-For'un SONUNA ekler (basi sahte olabilir)
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.remote_addr or "?"


def login_locked(ip):
    now = time.time()
    with _fail_lock:
        f = _fails.setdefault(ip, [])
        f[:] = [t for t in f if now - t < IP_WINDOW]
        _global_fails[:] = [t for t in _global_fails if now - t < GLOBAL_WINDOW]
        return len(f) >= MAX_FAILS_PER_IP or len(_global_fails) >= MAX_FAILS_GLOBAL


def register_fail(ip):
    now = time.time()
    with _fail_lock:
        _fails.setdefault(ip, []).append(now)
        _global_fails.append(now)
        return len(_fails[ip])


def _notify_async(message, title):
    threading.Thread(target=send_ntfy, args=(message,),
                     kwargs={"title": title, "priority": "high", "tags": "warning"},
                     daemon=True).start()


LOGIN_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>J.A.R.V.I.S. - Giris</title>
<link rel="icon" href="/favicon.ico" type="image/svg+xml">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#000; color:#00b4ff; font-family:'Courier New',monospace; display:flex;
       align-items:center; justify-content:center; min-height:100vh; }
.box { width:min(320px,90vw); text-align:center; }
.ring { width:110px; height:110px; margin:0 auto 22px; border-radius:50%;
        border:3px solid rgba(0,180,255,.25); border-top-color:#00d2ff; border-right-color:#ffbe00;
        display:flex; align-items:center; justify-content:center; font-weight:bold;
        letter-spacing:2px; font-size:12px; color:#00d2ff; }
input { width:100%; background:rgba(0,20,40,.8); color:#00b4ff; border:1px solid #00b4ff;
        padding:12px; border-radius:6px; font-size:18px; text-align:center;
        font-family:'Courier New',monospace; letter-spacing:4px; }
button { width:100%; margin-top:10px; background:#00b4ff; color:#000; border:none; padding:12px;
         border-radius:6px; font-size:16px; font-weight:bold; cursor:pointer; }
.err { color:#ff4444; margin-top:12px; font-size:13px; }
.hint { color:rgba(0,180,255,.5); margin-top:14px; font-size:11px; }
</style>
</head>
<body>
<div class="box">
  <div class="ring">J.A.R.V.I.S</div>
  <form method="POST" action="/login">
    <input type="password" name="pin" placeholder="PIN" autofocus autocomplete="current-password">
    <button type="submit">GIRIS</button>
  </form>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <div class="hint">Yetkili erisim</div>
</div>
</body>
</html>'''

app = Flask(__name__)

# ── YAMA_UYGULANDI_v1: oturum ayarlari + giris / cikis ──
app.secret_key = _load_secret()
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


@app.route("/login", methods=["POST"])
def login():
    ip = client_ip()
    if login_locked(ip):
        log_connection_event("GIRIS ENGELLENDI", "-", f"ip={ip}")
        return render_template_string(LOGIN_HTML, error="Cok fazla hatali deneme. Biraz bekle."), 429
    pin = (request.form.get("pin") or "").strip()
    if hmac.compare_digest(pin.encode("utf-8"), JARVIS_PIN.encode("utf-8")):
        session.clear()
        session["auth"] = True
        session.permanent = True
        log_connection_event("GIRIS BASARILI", "-", f"ip={ip}")
        return redirect("/")
    n = register_fail(ip)
    log_connection_event("HATALI PIN", "-", f"ip={ip}")
    if n == MAX_FAILS_PER_IP:
        _notify_async(f"{MAX_FAILS_PER_IP} hatali PIN denemesi, IP kilitlendi: {ip}", "JARVIS - Guvenlik")
    return render_template_string(LOGIN_HTML, error="Hatali PIN."), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/favicon.ico")
def favicon():
    return """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>
    <circle cx='50' cy='50' r='45' fill='black' stroke='#00b4ff' stroke-width='4'/>
    <text x='50' y='65' font-size='50' text-anchor='middle' fill='#00b4ff' font-family='Courier New' font-weight='bold'>J</text>
    </svg>""", 200, {'Content-Type': 'image/svg+xml'}

socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS)

# ══════════════════════════════════════════
#  YENI: ntfy.sh uzerinden telefona bildirim gonderme
# ══════════════════════════════════════════
NTFY_TOPIC = _gizli_oku("JARVIS_NTFY_TOPIC", r"C:\Jarvis\ntfy_topic.txt")

def send_ntfy(message, title=None, priority="default", tags=None):
    """Telefona ntfy.sh uzerinden push bildirimi gonderir.
    Bu fonksiyon hicbir zaman ana akisi durdurmaz; hata olursa sadece loglar."""
    try:
        headers = {}
        if title:
            headers["Title"] = title.encode("utf-8")
        if priority:
            headers["Priority"] = priority
        if tags:
            headers["Tags"] = tags
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=5,
        )
    except Exception as e:
        print("ntfy bildirimi gonderilemedi:", e)


# ══════════════════════════════════════════
#  YENI: Baglanti / ayrilma loglama
# ══════════════════════════════════════════
CONNECTION_LOG_PATH = r"C:\Jarvis\connection_log.txt"

def log_connection_event(event_type, sid, extra=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {event_type} - sid={sid} {extra}".strip()
    print(line)
    try:
        os.makedirs(os.path.dirname(CONNECTION_LOG_PATH), exist_ok=True)
        with open(CONNECTION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print("Baglanti logu dosyaya yazilamadi:", e)


@socketio.on("connect")
def handle_connect():
    ip = client_ip()
    if not session.get("auth"):
        log_connection_event("BAGLANTI REDDEDILDI", request.sid, f"ip={ip}")
        return False
    log_connection_event("BAGLANDI", request.sid, f"ip={ip}")
    send_ntfy(f"Web arayuzune yeni baglanti: {ip}", title="JARVIS - Baglanti", tags="link")


@socketio.on("disconnect")
def handle_disconnect():
    log_connection_event("AYRILDI", request.sid)


# ── YENI: JARVIS'in verdigi cevaplari web istemcilerine yayinlamak icin ──
def broadcast_response(text):
    """jarvis_voice.py -> speak() burayi cagirir, boylece web sayfasindaki
    sohbet paneli de JARVIS'in ne soyledigini gerceke zamanli gorur."""
    try:
        socketio.emit("response", {"text": text})
    except Exception as e:
        print("broadcast_response hata:", e)


def broadcast_status(state):
    """state: 'processing' | 'listening' | 'speaking' """
    try:
        socketio.emit("status", {"state": state})
    except Exception as e:
        print("broadcast_status hata:", e)


HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>J.A.R.V.I.S.</title>
    <link rel="icon" href="/favicon.ico" type="image/svg+xml">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #000; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; font-family: 'Courier New'; overflow: hidden; }
        canvas { display: block; }
       .controls { display: flex; gap: 8px; }
        input { flex: 1; background: rgba(0,20,40,200); color: #00b4ff; border: 1px solid #00b4ff; padding: 12px; border-radius: 6px; font-size: 16px; font-family: 'Courier New'; }
        button { background: #00b4ff; color: #000; border: none; padding: 12px 16px; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; }

        /* ── YENI: Acilis (boot) animasyonu ── */
        #bootOverlay {
            position: fixed; inset: 0; background: #000; z-index: 999;
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            transition: opacity 0.6s ease;
        }
        #bootOverlay.hide { opacity: 0; pointer-events: none; }
        #bootRing {
            width: 140px; height: 140px; border-radius: 50%;
            border: 3px solid rgba(0,180,255,0.2);
            border-top-color: #00d2ff; border-right-color: #ffbe00;
            animation: spin 1.1s linear infinite;
            display: flex; align-items: center; justify-content: center;
            margin-bottom: 24px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        #bootRing span { color: #00d2ff; font-weight: bold; font-size: 13px; letter-spacing: 2px; }
        #bootLines { color: #00b4ff; font-size: 12px; line-height: 22px; text-align: left; min-height: 110px; }
        #bootLines div { opacity: 0; animation: fadein 0.3s forwards; }
        @keyframes fadein { to { opacity: 1; } }

        /* ── YENI: Sohbet paneli ── */
        #chatPanel {
            position: fixed; left: 0; right: 0; bottom: 130px;
            max-height: 34vh; overflow-y: auto;
            padding: 8px 14px; display: flex; flex-direction: column; gap: 4px;
            pointer-events: none;
        }
        #chatPanel .msg { font-size: 12px; line-height: 16px; text-shadow: 0 0 4px rgba(0,0,0,0.9); }
        #chatPanel .you { color: #ffbe00; }
        #chatPanel .jarvis { color: #00d2ff; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <!-- ── YENI: Acilis animasyonu overlay ── -->
    <div id="bootOverlay">
        <div id="bootRing"><span>J.A.R.V.I.S</span></div>
        <div id="bootLines"></div>
    </div>

    <canvas id="jarvis"></canvas>

    <!-- ── YENI: Sohbet paneli ── -->
    <div id="chatPanel"></div>

    <div id="bottomPanel" style="position: fixed; bottom: 0; left: 0; width: 100%; display: flex; flex-direction: column; gap: 8px; padding: 10px; box-sizing: border-box; background: linear-gradient(to top, rgba(0,0,0,0.95), rgba(0,0,0,0.6) 70%, rgba(0,0,0,0));">
        <div class="btn-row" style="display: flex; gap: 8px;">
            <button id="micBtn" onclick="toggleMic()" style="flex:1; background:#111; border:1px solid #ff4444; color:#ff4444; padding:10px; border-radius:6px; font-family:'Courier New'; font-weight:bold;">● MIC ON</button>
            <button id="langBtn" onclick="toggleLang()" style="width:60px; background:#111; border:1px solid #00b4ff; color:#00b4ff; padding:10px; border-radius:6px; font-family:'Courier New'; font-weight:bold;">TR</button>
            <button id="camBtn" onclick="toggleCam()" style="flex:1; background:#111; border:1px solid #ff4444; color:#ff4444; padding:10px; border-radius:6px; font-family:'Courier New'; font-weight:bold;">● CAM ON</button>
        </div>
        <div class="controls" style="display: flex; gap: 8px;">
            <input type="text" id="cmd" placeholder="Komut yaz...">
            <button onclick="sendCmd()">▶</button>
        </div>
    </div>
    <video id="camPreview" autoplay muted playsinline style="position: fixed; top: 10px; right: 10px; width: 120px; border: 1px solid #00b4ff; display:none; z-index: 20;"></video>

    <script>

        // ══════════════════════════════════════════
        //  YENI: Acilis (boot) animasyonu
        // ══════════════════════════════════════════
        (function() {
            var lines = [
                "CONNECTING TO J.A.R.V.I.S CORE...",
                "SYNCING WITH LOCAL SYSTEM...",
                "VOICE CHANNEL ESTABLISHED...",
                "ALL SYSTEMS OPERATIONAL"
            ];
            var box = document.getElementById("bootLines");
            var i = 0;
            function nextLine() {
                if (i < lines.length) {
                    var d = document.createElement("div");
                    d.textContent = "> " + lines[i];
                    box.appendChild(d);
                    i++;
                    setTimeout(nextLine, 420);
                }
            }
            nextLine();
            setTimeout(function() {
                document.getElementById("bootOverlay").classList.add("hide");
            }, 2200);
        })();

        // ══════════════════════════════════════════
        //  YENI: basit bip sesleri (Web Audio API)
        // ══════════════════════════════════════════
        var audioCtx = null;
        function beep(freq, dur, vol) {
            try {
                if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                var osc = audioCtx.createOscillator();
                var gain = audioCtx.createGain();
                osc.frequency.value = freq;
                osc.type = "sine";
                gain.gain.value = vol || 0.05;
                osc.connect(gain); gain.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + dur / 1000);
            } catch (e) {}
        }
        function beepSend()     { beep(1000, 70, 0.05); beep(1400, 70, 0.05); }
        function beepResponse() { beep(1200, 60, 0.04); }

        var socket = io();
        var canvas = document.getElementById("jarvis");
        var ctx = canvas.getContext("2d");
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight - 80;

        var angle = 0, angle2 = 0, angle3 = 0, pulse = 0;
        var cx = canvas.width/2, cy = canvas.height/2;
        var r1 = Math.min(cx,cy) * 0.82;

        // ── YENI: gercek mikrofon seviyesi (0..1), core'u nabiz gibi buyutur ──
        var micLevel = 0;

        function drawRing(r, color, width, rot, dot) {
            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(rot);
            ctx.beginPath();
            ctx.arc(0, 0, r, 0, Math.PI*2);
            ctx.strokeStyle = color;
            ctx.lineWidth = width;
            ctx.stroke();
            if(dot) {
                ctx.beginPath();
                ctx.arc(0, -r, 5, 0, Math.PI*2);
                ctx.fillStyle = color;
                ctx.fill();
            }
            ctx.restore();
        }

        function draw() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = "#000";
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // Grid
            ctx.strokeStyle = "rgba(0,180,255,0.05)";
            ctx.lineWidth = 1;
            for(var x=0; x<canvas.width; x+=40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,canvas.height); ctx.stroke(); }
            for(var y=0; y<canvas.height; y+=40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(canvas.width,y); ctx.stroke(); }

            // mikrofon seviyesine gore nabiz eklentisi
            var pulseR = r1 * (1 + micLevel * 0.10);

            // Rings
            drawRing(pulseR, "rgba(0,180,255,0.6)", 2 + micLevel*3, angle, true);
            drawRing(pulseR*0.85, "rgba(0,180,255,0.3)", 1, angle2, true);
            drawRing(pulseR*0.70, "rgba(255,200,0,0.5)", 3, angle3, false);
            drawRing(pulseR*0.56, "rgba(0,180,255,0.2)", 1, -angle2, false);

            // Ticks
            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(angle);
            for(var i=0; i<60; i++) {
                var a = i*6*Math.PI/180;
                var lng = i%5===0;
                var l = lng ? 14 : 7;
                ctx.beginPath();
                ctx.moveTo(Math.sin(a)*(r1-l), -Math.cos(a)*(r1-l));
                ctx.lineTo(Math.sin(a)*r1, -Math.cos(a)*r1);
                ctx.strokeStyle = lng ? "rgba(0,180,255,0.8)" : "rgba(0,180,255,0.4)";
                ctx.lineWidth = 1.5;
                ctx.stroke();
            }
            ctx.restore();

            // Core (mikrofon seviyesine gore parlar)
            var grad = ctx.createRadialGradient(cx,cy,0,cx,cy,r1*0.46 + micLevel*20);
            grad.addColorStop(0, "rgba(0," + (40+micLevel*140) + ",80,0.7)");
            grad.addColorStop(1, "rgba(0,0,0,0)");
            ctx.beginPath();
            ctx.arc(cx,cy,r1*0.46 + micLevel*20,0,Math.PI*2);
            ctx.fillStyle = grad;
            ctx.fill();

            // Text
            ctx.fillStyle = "rgba(0,180,255,0.9)";
            ctx.font = "bold " + Math.max(14,r1*0.10) + "px 'Courier New'";
            ctx.textAlign = "center";
            ctx.fillText("J.A.R.V.I.S", cx, cy);
            ctx.font = Math.max(10,r1*0.06) + "px 'Courier New'";
            ctx.fillStyle = "rgba(0,180,255,0.5)";
            ctx.fillText("ONLINE", cx, cy+20);

            angle += 0.005;
            angle2 -= 0.003;
            angle3 += 0.01;
            pulse = (pulse+0.02)%1;
            // mikrofon sesi yoksa yavasca sifira in
            micLevel *= 0.9;
            requestAnimationFrame(draw);
        }
        draw();

        // ══════════════════════════════════════════
        //  YENI: Sohbet paneli
        // ══════════════════════════════════════════
        function addMsg(sender, text) {
            var panel = document.getElementById("chatPanel");
            var d = document.createElement("div");
            d.className = "msg " + (sender === "You" ? "you" : "jarvis");
            d.textContent = sender + ": " + text;
            panel.appendChild(d);
            panel.scrollTop = panel.scrollHeight;
            // en fazla 20 mesaj tut
            while (panel.children.length > 20) panel.removeChild(panel.firstChild);
        }

        socket.on("response", function(data) {
            addMsg("JARVIS", data.text);
            beepResponse();
        });

        function sendCmd() {
            var cmd = document.getElementById("cmd").value;
            if(cmd) {
                addMsg("You", cmd);
                beepSend();
                socket.emit("command", {text: cmd});
                document.getElementById("cmd").value = "";
            }
        }
        document.getElementById("cmd").addEventListener("keypress", function(e) {
            if(e.key === "Enter") sendCmd();
        });

    // ── Mikrofon (Speech-to-Text + gercek seviye olcumu) ──
var recognizing = false;
var recognition;
var currentLang = "tr-TR";
var micAnalyser = null, micRawStream = null;

if ('webkitSpeechRecognition' in window) {
    recognition = new webkitSpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = currentLang;

    recognition.onresult = function(event) {
        var lastResult = event.results[event.results.length - 1];
        var text = lastResult[0].transcript.trim();
        if (text) {
            addMsg("You", text);
            socket.emit("command", {text: text});
        }
    };
    recognition.onend = function() {
        if (recognizing) recognition.start();
    };
}

function toggleLang() {
    var btn = document.getElementById("langBtn");
    if (currentLang === "tr-TR") {
        currentLang = "en-US";
        btn.innerText = "EN";
    } else {
        currentLang = "tr-TR";
        btn.innerText = "TR";
    }
    if (recognition) {
        recognition.lang = currentLang;
        if (recognizing) {
            recognition.stop();
            recognition.start();
        }
    }
}

// ── YENI: gercek mikrofon seviyesini olcup core'u nabiz gibi buyuten kisim ──
function startMicLevelMeter() {
    if (micAnalyser) return; // zaten calisiyor
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
        micRawStream = stream;
        var ac = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        audioCtx = ac;
        var source = ac.createMediaStreamSource(stream);
        var analyser = ac.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        micAnalyser = analyser;
        var data = new Uint8Array(analyser.frequencyBinCount);
        (function tick() {
            if (!micAnalyser) return;
            analyser.getByteTimeDomainData(data);
            var sum = 0;
            for (var i = 0; i < data.length; i++) {
                var v = (data[i] - 128) / 128;
                sum += v * v;
            }
            var rms = Math.sqrt(sum / data.length);
            micLevel = Math.max(micLevel, Math.min(1, rms * 4));
            requestAnimationFrame(tick);
        })();
    }).catch(function(e) { console.log("Mikrofon seviyesi alinamadi:", e); });
}

function stopMicLevelMeter() {
    if (micRawStream) {
        micRawStream.getTracks().forEach(function(t){ t.stop(); });
        micRawStream = null;
    }
    micAnalyser = null;
}

function toggleMic() {
    var btn = document.getElementById("micBtn");
    if (!recognition) {
        alert("Bu tarayıcı mikrofonla ses tanımayı desteklemiyor (Chrome kullan).");
        return;
    }

    if (!recognizing) {
        recognition.start();
        recognizing = true;
        startMicLevelMeter();
        btn.style.background = "#ff4444";
        btn.style.color = "#000";
        btn.innerText = "● MIC LISTENING"; 
    } else {
        recognition.stop();
        recognizing = false;
        stopMicLevelMeter();
        btn.style.background = "#111";
        btn.style.color = "#ff4444";
        btn.innerText = "● MIC ON";
    }
}
    // ── Kamera ──
        var camStream = null;
        function toggleCam() {
            var btn = document.getElementById("camBtn");
            var video = document.getElementById("camPreview");
            if (!camStream) {
                navigator.mediaDevices.getUserMedia({ video: true })
                    .then(function(stream) {
                        camStream = stream;
                        video.srcObject = stream;
                        video.style.display = "block";
                        btn.style.background = "#ff4444";
                        btn.style.color = "#000";
                        btn.innerText = "● CAM ON";
                    })
                    .catch(function(err) {
                        alert("Kameraya erişilemedi: " + err);
                    });
            } else {
                camStream.getTracks().forEach(t => t.stop());
                camStream = null;
                video.style.display = "none";
                btn.style.background = "#111";
                btn.style.color = "#ff4444";
                btn.innerText = "● CAM ON";
            }
        }

    // ── Ekran Paylaşımı ──
var screenInterval = null;

function toggleScreen() {
    var panel = document.getElementById("screenPanel");
    if (panel.style.display === "none" || panel.style.display === "") {
        panel.style.display = "flex";
        screenInterval = setInterval(function() {
            document.getElementById("screenImg").src = "/screen?" + Date.now();
        }, 200);
    } else {
        stopScreen();
    }
}

function stopScreen() {
    document.getElementById("screenPanel").style.display = "none";
    if (screenInterval) { clearInterval(screenInterval); screenInterval = null; }
}

    </script>

        <!-- Ekran Paylaşımı -->
    <div id="screenPanel" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:#000; z-index:50; flex-direction:column;">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:10px; border-bottom:1px solid #00b4ff;">
            <span style="color:#00b4ff; font-family:'Courier New'; font-size:14px;">● SCREEN SHARE</span>
            <button onclick="stopScreen()" style="background:#ff4444; color:#000; border:none; padding:8px 14px; border-radius:6px; font-weight:bold; cursor:pointer;">✕ KAPAT</button>
        </div>
        <img id="screenImg" style="width:100%; height:calc(100% - 50px); object-fit:contain;" />
    </div>
    <button onclick="toggleScreen()" style="position:fixed; top:10px; left:10px; background:#111; border:1px solid #00b4ff; color:#00b4ff; padding:8px 12px; border-radius:6px; font-family:'Courier New'; font-size:12px; z-index:30; cursor:pointer;">🖥 EKRAN</button>

</body>
</html>
'''

import mss
import mss.tools
from PIL import Image as PILImage

@app.route("/screen")
def screen():
    if not session.get("auth"):
        return "unauthorized", 401
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = PILImage.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img.thumbnail((800, 500))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            buf.seek(0)
            response = app.response_class(
                buf.read(),
                mimetype="image/jpeg"
            )
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            return response
    except Exception as e:
        return str(e), 500
    
@app.route("/")
def index():
    if not session.get("auth"):
        return render_template_string(LOGIN_HTML, error="")
    return render_template_string(HTML)

@socketio.on("command")
def handle_command(data):
    if not session.get("auth"):
        return
    from jarvis_voice import process_command
    text = str(data.get("text", "") if isinstance(data, dict) else "").strip()[:300]
    if not text:
        return
    log_connection_event("KOMUT", request.sid, f"text={text!r}")
    broadcast_status("processing")
    threading.Thread(target=process_command, args=(text,), daemon=True).start()

import ngrok

# ══════════════════════════════════════════
#  YENI: ngrok token artik kod icinde degil, ortam degiskeninden okunuyor.
#  Windows'ta kalici olarak ayarlamak icin (CMD, tek seferlik):
#     setx NGROK_AUTHTOKEN "buraya-token-in"
#  Ayarladiktan sonra terminali/CMD'yi kapatip yeniden acman gerekir.
# ══════════════════════════════════════════
NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN")

def start_server():
    if not NGROK_AUTHTOKEN:
        raise RuntimeError(
            "NGROK_AUTHTOKEN ortam degiskeni ayarlanmamis. "
            "CMD'de 'setx NGROK_AUTHTOKEN \"token-in\"' calistirip "
            "terminali yeniden ac."
        )

    listener = ngrok.forward(
        5000,
        authtoken=NGROK_AUTHTOKEN,
        domain=NGROK_DOMAIN
    )
    url = listener.url()
    open(r"C:\Jarvis\jarvis_url.txt", "w").write(url)
    print(f"JARVIS URL: {url}")

    # ── YENI: bilgisayar acildiginda / server basladiginda telefona bildirim ──
    send_ntfy(
        f"JARVIS baslatildi.\nURL: {url}",
        title="JARVIS Aktif",
        priority="high",
        tags="rocket,white_check_mark",
    )
    log_connection_event("SERVER BASLATILDI", "-", f"url={url}")

    import phone_listener
    phone_listener.start_phone_listener()

    socketio.run(app, port=5000, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    start_server()