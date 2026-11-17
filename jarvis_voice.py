import os
# --- YAZI GORUNMEME SORUNU ICIN: PyQt5 import edilmeden ONCE ayarlanmali ---
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

import sys
import threading
import time
import math
import random
import webbrowser
import datetime
import json
import subprocess
import requests
import tempfile
import numpy as np
import pyaudio
import vlc
import traceback
import queue

import speech_recognition as sr
import psutil
import edge_tts
import asyncio
import re
import wmi

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QSystemTrayIcon,
                              QMenu, QAction, QLineEdit, QPushButton, QVBoxLayout,
                              QHBoxLayout, QFrame, QLabel)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont, QIcon, QPixmap, QRadialGradient

from jarvis_shared import Signals, signals, JarvisFace

# ── Iron Man tarzi efektler (boot animasyonu, gercek ses dalgasi,
#     dairesel menu, bip sesleri) - jarvis_effects.py ayni klasorde olmali ──
import jarvis_effects as fx


def kill_previous_instances():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any('jarvis_voice.py' in str(c) for c in cmdline) and proc.info['pid'] != current_pid:
                print(f"Eski JARVIS örneği kapatılıyor (PID {proc.info['pid']})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


vlc_instance = vlc.Instance()
vlc_player = vlc_instance.media_list_player_new()
music_playing = False
is_speaking = threading.Event()

# ── Araya girme: sen konusunca JARVIS susar; yarim cumleyi yanlis anlamasin ──
konusma_dur = threading.Event()   # set edilirse JARVIS konusmayi hemen keser
BARGE_IN = True                   # False: sen konusunca JARVIS susmasin (hoparlorle kendi sesine tepki verirse False yap)
BARGE_SEVIYE = 0.45               # mikrofon seviyesi (0..1); kendi sesine tepki veriyorsa artir (0.6), duymuyorsa azalt (0.3)
BARGE_SURE = 0.35                 # bu kadar sn surekli yuksek ses olursa JARVIS susar
YARIM_BIRLESTIR = True            # JARVIS susturulunca ya da cevap iptal olunca 10 sn icindeki yeni cumleyi eskisiyle birlestir
_speak_basla_t = [0.0]
_cevap_no = {"n": 0}              # her yapay zeka sorusuna numara; yeni soru gelince eski cevap iptal olur
_bekleyen = {"metin": "", "t": 0.0}
speak_lock = threading.Lock()  # ayni anda tek konusma olsun; JARVIS konusurken mikrofon susturulur

# ══════════════════════════════════════════
#  SES AYARLARI
# ══════════════════════════════════════════
VARSAYILAN_SES = "tr-TR-EmelNeural"   # tum konusmalarin varsayilan sesi 
JARVIS_OKUNUS = "Jaarvis"   # sesin "Jarvis"i doğru okuması için okunuş
EDGE_TIMEOUT = 12                     # Edge TTS'in cevap vermesi icin saniye
EDGE_DENEME = 2                        # basarisiz olursa kac kez denesin
EDGE_BEKLEME = 60                    # Edge basarisiz olursa kac saniye boyunca hic denenmesin
GTTS_TIMEOUT = 10                      # Google yedek sesi icin saniye
EDGE_HIZ = "+5%"      # konuşma hızı (yavaş geliyorsa artır)
EDGE_PERDE = "+0Hz" # ses inceliği
print("edge-tts surumu:", getattr(edge_tts, "__version__", "bilinmiyor"))   # guncel degilse: pip install -U edge-tts

# ══════════════════════════════════════════
#  YAMA_UYGULANDI_v1: modul takma adi, komut esleme, onay, dinleyiciler
# ══════════════════════════════════════════
# jarvis_voice.py dogrudan calistirilinca modul adi "__main__" olur. Diger dosyalar
# "import jarvis_voice" deyince bu dosya ikinci kez yuklenip AYRI bir kopya olusuyordu.
# Bu satir ikisini birlestirir.
if __name__ == "__main__":
    sys.modules["jarvis_voice"] = sys.modules[__name__]

response_callbacks = []   # speak() her konustugunda cagrilir (dashboard dinler)

_TR_MAP = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def normalize(text):
    # Kucuk harfe cevirir, Turkce harfleri ASCII yapar (ç->c, ş->s ...)
    return text.replace("İ", "i").lower().translate(_TR_MAP)


def tr_upper(text):
    # Ekranda gorunen yazi icin Turkce'ye uygun buyuk harf (i -> İ, ı -> I)
    return text.replace("i", "İ").replace("ı", "I").upper()


def has(text, *phrases):
    # Komut eslestirme. Bosluklu / uzun ifadeler ("ekran goruntusu", "whatsapp")
    # ek alabilir ("ekran goruntusunu al"). Kisa tek kelimeler ("hava", "ses", "saat")
    # TAM KELIME olmali; boylece "havali" hava durumunu tetiklemez.
    for p in phrases:
        p = normalize(p)
        if " " in p or len(p) >= 8:
            pattern = r"(?<!\w)" + re.escape(p)
        else:
            pattern = r"(?<!\w)" + re.escape(p) + r"(?!\w)"
        if re.search(pattern, text):
            return True
    return False


# ── Tehlikeli komutlar icin "emin misin?" onayi ──
CONFIRM_TIMEOUT = 15
YES_WORDS = {"evet", "yes", "onayla", "onayliyorum", "confirm", "tamam", "olur"}
NO_WORDS = {"hayir", "no", "iptal", "cancel", "vazgec", "dur"}
_pending = None
_pending_lock = threading.Lock()


def ask_confirmation(description, action):
    global _pending
    with _pending_lock:
        _pending = (action, float("inf"))
    speak(f"{description} Emin misin? Onaylamak için evet, iptal için hayır de.")
    with _pending_lock:
        if _pending is not None and _pending[0] is action:
            _pending = (action, time.time() + CONFIRM_TIMEOUT)


def _handle_pending(komut):
    # True donerse komut onay/iptal olarak kullanildi, normal isleme devam etme.
    global _pending
    with _pending_lock:
        pending = _pending
        if pending is None:
            return False
        action, expiry = pending
        _pending = None
        if time.time() > expiry:
            return False
        words = set(re.findall(r"\w+", komut))
        if words & NO_WORDS:
            confirmed = False
        elif words & YES_WORDS:
            confirmed = True
        else:
            return False   # baska bir sey soylendi: onay iptal, komut normal islenir
    if confirmed:
        action()
    else:
        speak("İptal edildi.")
    return True


def _do_shutdown():
    speak("Bilgisayar kapanıyor. Görüşürüz Zeynep.")
    os.system("shutdown /s /t 5")


def _do_close_everything():
    for exe in ["chrome.exe", "steam.exe", "vlc.exe", "YouTubeMusic.exe", "Discord.exe",
                "UnityHub.exe", "Unity.exe", "Code.exe", "PhoneExperienceHost.exe",
                "notepad.exe", "WindowsTerminal.exe", "WhatsApp.exe"]:
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True)
    speak("Tüm uygulamalar kapatıldı Zeynep.")


def _do_wifi_off():
    wifi_toogle(False)
    speak("Kablosuz bağlantı kapatıldı.")


# ══════════════════════════════════════════
#  KONUSMA (Edge TTS + VLC, yedek: Windows sesi)
# ══════════════════════════════════════════
async def _edge_kaydet(metin, ses, yol, timeout):
    communicate = edge_tts.Communicate(metin, voice=ses, rate=EDGE_HIZ, pitch=EDGE_PERDE)
    await asyncio.wait_for(communicate.save(yol), timeout=timeout)


# Microsoft Edge sesine erisimi (403) kapatirsa her konusmada bosuna beklememek icin
# bir sure hic denenmez, dogrudan yedek sese gecilir; sure dolunca tekrar denenir.
_edge_kapali_bitis = 0.0

# Multilingual sesler (Ava vb.) ilk istekte 6-11 sn surebiliyor, sonra 1-2 sn. Bu yuzden
# acilista ve bosta kalinca kucuk bir istek atip sesi "sicak" tutuyoruz.
EDGE_ISINMA_ARALIK = 240      # sn: bu kadar suredir ses uretilmediyse sesi tekrar isit
_son_edge_kullanim = time.time()


def _edge_ile_kaydet(clean, ses, yol):
    global _edge_kapali_bitis, _son_edge_kullanim
    if time.time() < _edge_kapali_bitis:
        return False
    for deneme in range(1, EDGE_DENEME + 1):
        t0 = time.time()
        try:
            asyncio.run(_edge_kaydet(clean, ses, yol, EDGE_TIMEOUT))
            if os.path.getsize(yol) > 0:
                _son_edge_kullanim = time.time()
                return True
        except Exception as e:
            durum = getattr(e, "status", "")
            print(f"Edge TTS hata (deneme {deneme}, ses={ses}, {len(clean)} karakter, "
                  f"{time.time() - t0:.1f} sn sonra): {type(e).__name__} {durum} {e}")
            if durum == 403:
                break   # Microsoft reddediyor; ayni istegi tekrarlamanin anlami yok
            time.sleep(0.7)   # hemen tekrar vurma, baglanti toparlansin
    _edge_kapali_bitis = time.time() + EDGE_BEKLEME
    print(f"Edge TTS {EDGE_BEKLEME // 60} dakika denenmeyecek, yedek ses kullanilacak.")
    return False


def _gtts_ile_kaydet(clean, ses, yol):
    # Yedek 1: Google'in ucretsiz sesi (pip install gTTS). Dil, istenen sesten alinir (tr-TR -> tr).
    try:
        from gtts import gTTS
    except ImportError:
        print("gTTS kurulu degil (pip install gTTS), bu yedek atlaniyor.")
        return False
    sonuc = {"ok": False}

    def _calis():
        try:
            gTTS(text=clean, lang="tr").save(yol)
            sonuc["ok"] = os.path.getsize(yol) > 0
        except Exception as e:
            print("gTTS hata:", type(e).__name__, e)

    t = threading.Thread(target=_calis, daemon=True)
    t.start()
    t.join(GTTS_TIMEOUT)
    return sonuc["ok"] and not t.is_alive()


def _vlc_ile_cal(yol):
    p = vlc_instance.media_player_new()
    try:
        p.set_media(vlc_instance.media_new(yol))
        p.play()
        t0 = time.time()
        while not p.is_playing() and time.time() - t0 < 3:   # calmaya baslamasini bekle
            time.sleep(0.05)
        while p.is_playing():
            if konusma_dur.is_set():
                p.stop()
                break
            time.sleep(0.05)
    finally:
        try:
            p.release()
        except Exception:
            pass


def _windows_sesi_ile_oku(clean, secilen_ses):
    # Yedek 2: internet gerekmeyen Windows sesi. Turkce ses istendiyse
    # Windows'taki Turkce sesi (varsa) secmeye calisir.
    kultur = ""
    if secilen_ses.lower().startswith("tr-") or "multilingual" in secilen_ses.lower():
        kultur = ("try { $s.SelectVoiceByHints('NotSet','NotSet',0,"
                  "[System.Globalization.CultureInfo]'tr-TR') } catch {}; ")
    script = ("Add-Type -AssemblyName System.speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              + kultur + "$s.Speak('" + clean + "')")
    try:
        subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", script],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        print("Windows sesi hata:", e)


def _edge_isit():
    """Kisa bir cumleyi sese cevirir (calmaz, atar). Hata olursa sessizce gecer."""
    global _son_edge_kullanim
    if time.time() < _edge_kapali_bitis:
        return
    yol = os.path.join(tempfile.gettempdir(), "jarvis_isinma.mp3")
    t0 = time.time()
    try:
        asyncio.run(_edge_kaydet("Merhaba", VARSAYILAN_SES, yol, EDGE_TIMEOUT))
        _son_edge_kullanim = time.time()
        print(f"[SURE] Ses isitildi ({VARSAYILAN_SES}): {time.time() - t0:.1f} sn")
    except Exception as e:
        print("Ses isitma basarisiz (onemli degil):", type(e).__name__)
    try:
        os.remove(yol)
    except Exception:
        pass


def _edge_isinma_dongusu():
    _edge_isit()                                   # acilista bir kez
    while True:
        time.sleep(30)
        if time.time() - _son_edge_kullanim >= EDGE_ISINMA_ARALIK:
            _edge_isit()


def _gecici_yol():
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir=r"C:\Jarvis")
    except Exception:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    yol = tmp.name
    tmp.close()
    return yol


def _metni_parcala(metin, hedef=130):
    """Metni cumle sinirlarinda kisa parcalara boler. Ilk parca kisa kalir ki ses hemen baslasin;
    sonraki parcalar sen dinlerken arka planda uretilir."""
    cumleler = re.split(r"(?<=[.!?…])(?<!\d\.)\s+|\n+", metin.strip())
    parcalar = []
    for c in cumleler:
        c = c.strip()
        if not c:
            continue
        while len(c) > hedef * 1.6:   # cok uzun cumleyi virgul/bosluktan bol
            sinir = int(hedef * 1.3)
            kes = max(c.rfind(",", 0, sinir), c.rfind(" ", 0, sinir))
            if kes < 40:
                kes = sinir
            parcalar.append(c[:kes + 1].strip())
            c = c[kes + 1:].strip()
        if c:
            parcalar.append(c)
    birlesik = []
    for c in parcalar:
        # ilk parca tek basina kalir, sonrakiler kisaysa birlestirilir
        if len(birlesik) > 1 and len(birlesik[-1]) + len(c) < hedef:
            birlesik[-1] += " " + c
        else:
            birlesik.append(c)
    return birlesik or [metin]


def fish_speak(text, voice=None, on_start=None):
    # (Adi eski kaldi.) Metin parcalara bolunur; bir parca calarken siradaki uretilir.
    # Her parca icin sira: Edge TTS -> Google gTTS -> Windows sesi
    secilen_ses = voice if voice else VARSAYILAN_SES
    clean = text.replace("'", "").replace('"', '').replace('`', '').replace('$', '')
    clean = re.sub(r"(?i)jarvis", JARVIS_OKUNUS, clean)
    parcalar = _metni_parcala(clean)

    _bildirildi = []

    def _basla():
        if not _bildirildi:
            _bildirildi.append(1)
            if on_start:
                try:
                    on_start()
                except Exception:
                    pass

    kuyruk = queue.Queue()

    def _uret():
        for parca in parcalar:
            if konusma_dur.is_set():
                break
            yol = _gecici_yol()
            ok = False
            try:
                for motor in (_edge_ile_kaydet, _gtts_ile_kaydet):
                    if motor(parca, secilen_ses, yol):
                        ok = True
                        break
            except Exception as e:
                print("ses uretim hata:", e)
            if not ok:
                try:
                    os.remove(yol)
                except Exception:
                    pass
            kuyruk.put((parca, yol if ok else None))
        kuyruk.put(None)

    t0 = time.time()
    threading.Thread(target=_uret, daemon=True).start()
    ilk = True
    while True:
        oge = kuyruk.get()
        if oge is None:
            break
        parca, yol = oge
        if konusma_dur.is_set():
            if yol:
                try:
                    os.remove(yol)
                except Exception:
                    pass
            continue   # kalan parcalari at, uretici bitince None gelir
        try:
            if ilk:
                ilk = False
                print(f"[SURE] Ilk ses parcasi hazir: {time.time() - t0:.1f} sn "
                      f"({len(parcalar)} parca, {len(clean)} karakter)")
            _basla()
            if yol:
                _vlc_ile_cal(yol)
            else:
                print("Internet seslerinin hicbiri calismadi, Windows sesine geciliyor.")
                _windows_sesi_ile_oku(parca, secilen_ses)
        except Exception as e:
            print("fish_speak hata:", e)
        finally:
            if yol:
                try:
                    os.remove(yol)
                except Exception:
                    pass


# ── Window ──
class JarvisWindow(QMainWindow):
    # Arka plan thread'leri arayuze DOGRUDAN dokunmaz, bu sinyallerle veri yollar
    stats_ready = pyqtSignal(dict)
    hand_state = pyqtSignal(bool)      # el modu acildi / kapandi (dugme rengi icin)
    remote_ready = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S.")
        self.setFixedSize(250, 590)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Ana widget
        central = QWidget()
        central.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # JARVIS yüzü
        self.face = JarvisFace()
        self.face.setFixedSize(250, 250)
        layout.addWidget(self.face)

        # Yazma kutusu
        input_frame = QFrame()
        input_frame.setStyleSheet("background: rgba(0,0,0,200); border-top: 1px solid rgba(0,180,255,100);")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(6, 4, 6, 4)
        input_layout.setSpacing(4)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Komut yaz...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background: rgba(0,20,40,200);
                color: #00b4ff;
                border: 1px solid rgba(0,180,255,150);
                border-radius: 4px;
                padding: 4px 8px;
                font-family: 'Courier New';
                font-size: 11px;
            }
        """)
        self.input_box.returnPressed.connect(self.send_text)

        send_btn = QPushButton("▶")
        send_btn.setFixedSize(28, 28)
        send_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,180,255,150);
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(0,180,255,220);
            }
        """)
        send_btn.clicked.connect(self.send_text)

        qr_btn = QPushButton("QR")
        qr_btn.setFixedSize(28, 28)
        qr_btn.setStyleSheet("""
    QPushButton {
        background: rgba(255,200,0,150);
        color: black;
        border: none;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
    }
    QPushButton:hover {
        background: rgba(255,200,0,220);
    }
""")
        qr_btn.clicked.connect(self.show_qr)
        expand_btn = QPushButton("⛶")
        expand_btn.setFixedSize(28, 28)
        expand_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,180,255,150);
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(0,180,255,220);
            }
        """)
        expand_btn.clicked.connect(self.show_dashboard)
        expand_btn.clicked.connect(self._bring_front)

        # Dairesel hologram menu butonu
        menu_btn = QPushButton("⊙")
        menu_btn.setFixedSize(28, 28)
        menu_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,190,0,150);
                color: black;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255,190,0,220);
            }
        """)
        menu_btn.clicked.connect(self.show_radial_menu)

        input_layout.addWidget(qr_btn)
        input_layout.addWidget(expand_btn)
        input_layout.addWidget(menu_btn)

        input_layout.addWidget(self.input_box)
        input_layout.addWidget(send_btn)
        layout.addWidget(input_frame)

        # Gercek mikrofon seviyesine tepki veren ses dalgasi
        wave_frame = QFrame()
        wave_frame.setStyleSheet("background: rgba(0,0,0,200); border-top: 1px solid rgba(0,180,255,60);")
        wave_layout = QVBoxLayout(wave_frame)
        wave_layout.setContentsMargins(6, 4, 6, 4)
        self.wave = fx.WaveWidget()
        wave_layout.addWidget(self.wave)
        layout.addWidget(wave_frame)

        # Monitor panel
        monitor_frame = QFrame()
        monitor_frame.setStyleSheet("background: rgba(0,0,0,200); border-top: 1px solid rgba(0,180,255,60);")
        monitor_layout = QVBoxLayout(monitor_frame)
        monitor_layout.setContentsMargins(8, 6, 8, 6)
        monitor_layout.setSpacing(3)

        self.lbl_cpu   = QLabel("CPU:  --%")
        self.lbl_ram   = QLabel("RAM:  --%")
        self.lbl_disk  = QLabel("DISK: --%")
        self.lbl_gpu   = QLabel("GPU:  --")
        self.lbl_net   = QLabel("NET:  --")
        self.lbl_temp  = QLabel("TEMP: --°C")
        self.lbl_bat   = QLabel("PIL:  --%")
        self.lbl_up    = QLabel("UP:   --")
        self.lbl_remote = QLabel("REMOTE: CHECKING...")

        style = "color: #00b4ff; font-family: 'Courier New'; font-size: 10px;"
        for lbl in [self.lbl_cpu, self.lbl_ram, self.lbl_disk, self.lbl_gpu,
                    self.lbl_net, self.lbl_temp, self.lbl_bat, self.lbl_up, self.lbl_remote]:
            lbl.setStyleSheet(style)
            monitor_layout.addWidget(lbl)

        layout.addWidget(monitor_frame)

        # Thread -> arayuz baglantilari (timer'lardan ONCE baglanmali)
        self.stats_ready.connect(self._apply_stats)
        self.remote_ready.connect(self._apply_remote)

        # Timer
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(lambda: threading.Thread(target=self.update_monitor, daemon=True).start())
        self.monitor_timer.start(3000)
        self.remote_timer = QTimer()
        self.remote_timer.timeout.connect(lambda: threading.Thread(target=self.check_remote_status, daemon=True).start())
        self.remote_timer.start(5000)

        # Sag ust kose: yari seffaf kapatma butonu (tum JARVIS'i kapatir)
        self.close_btn = QPushButton("✕", central)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.move(250 - 24 - 8, 8)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("JARVIS'i kapat")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0,0,0,70);
                color: rgba(0,180,255,190);
                border: 1px solid rgba(0,180,255,80);
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255,60,60,170);
                color: white;
                border: 1px solid rgba(255,120,120,200);
            }
        """)
        self.close_btn.clicked.connect(self.quit_all)
        self.close_btn.raise_()

        # kapatma butonunun solunda: el modu ac/kapat dugmesi (acikken parlar, kamera penceresi acilir)
        self.hand_btn = QPushButton("\u270B", central)
        self.hand_btn.setFixedSize(24, 24)
        self.hand_btn.move(250 - 24 - 8 - 28, 8)
        self.hand_btn.setCursor(Qt.PointingHandCursor)
        self.hand_btn.setToolTip("El modu: aç / kapat")
        self._apply_hand(False)
        self.hand_btn.clicked.connect(
            lambda: threading.Thread(target=_gesture_toggle, daemon=True).start())
        self.hand_state.connect(self._apply_hand)
        self.hand_btn.raise_()

        self.setCentralWidget(central)

        sc = QApplication.primaryScreen().geometry()
        self.move(sc.width() - 270, 20)

        signals.set_status.connect(self.face.set_status)
        signals.set_text.connect(self.face.set_label)
        signals.set_heard.connect(self.face.set_label)
        signals.show_ui.connect(self._bring_front)
        signals.hide_ui.connect(self._send_back)
        self.face.clicked.connect(self.toogle_topmost)
        self.show()

    def _apply_hand(self, on):
        if on:
            css = ("QPushButton { background: rgba(0,180,255,150); color: white; "
                   "border: 1px solid rgba(120,220,255,220); border-radius: 12px; font-size: 12px; }")
        else:
            css = ("QPushButton { background: rgba(0,0,0,70); color: rgba(0,180,255,190); "
                   "border: 1px solid rgba(0,180,255,80); border-radius: 12px; font-size: 12px; } "
                   "QPushButton:hover { background: rgba(0,180,255,90); color: white; }")
        self.hand_btn.setStyleSheet(css)

    def quit_all(self):
        """Tum JARVIS'i kapatir: arayuz, sunucu, alt surecler (ngrok vb.)."""
        try:
            _gesture.stop()   # kamerayi serbest birak
        except Exception:
            pass
        try:
            stop_music()
        except Exception:
            pass
        try:
            for child in psutil.Process().children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
        except Exception:
            pass
        QApplication.quit()
        # arka plan thread'leri (mikrofon, sunucu) takilirsa diye kesin cikis
        QTimer.singleShot(600, lambda: os._exit(0))

    def toogle_topmost(self):
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.show()
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self.show()
            self.raise_()

    def send_text(self):
        text = self.input_box.text().strip()
        if text:
            self.input_box.clear()
            signals.process_text.emit(text)

    def _bring_front(self):
        self.show()
        self.raise_()   # sadece one getir, zorla "her zaman ustte" yapma

    def _send_back(self):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.show()

    # ── Dairesel hologram komut menusunu ac ──
    def show_radial_menu(self):
        try:
            items = [
                ("MUZIK", "muzik cal"),
                ("HAVA", "hava durumu"),
                ("DURUM", "sistem durumu"),
                ("EKRAN", "ekran goruntusu"),
                ("KILITLE", "kilitle"),
                ("NOTEPAD", "not defteri"),
                ("KOYU MOD", "karanlik mod"),
                ("TAKVIM", "takvime ekle"),
            ]
            self._radial = fx.RadialMenu(items, on_select=lambda cmd: signals.process_text.emit(cmd))
            self._radial.show()
        except Exception as e:
            print("Radial menu hata:", e)
            traceback.print_exc()

    # Bu fonksiyon ayri thread'de calisir: arayuze DOKUNMAZ, sadece sinyal yollar.
    def update_monitor(self):
        try:
            d = {}
            d["cpu"] = f"CPU:  {psutil.cpu_percent():.0f}%"
            d["ram"] = f"RAM:  {psutil.virtual_memory().percent:.0f}%"
            d["disk"] = f"DISK: {psutil.disk_usage('/').percent:.0f}%"
            net = psutil.net_io_counters()
            d["net"] = f"NET:  ↓{net.bytes_recv / 1024 / 1024:.1f}MB"

            bat = psutil.sensors_battery()
            if bat:
                pil = int(bat.percent)
                if bat.power_plugged:
                    d["bat"] = f"PIL:  {pil}% ⚡"
                else:
                    secs = bat.secsleft
                    if secs and secs > 0:
                        d["bat"] = f"PIL:  {pil}% ({secs // 3600}s{(secs % 3600) // 60}d)"
                    else:
                        d["bat"] = f"PIL:  {pil}%"

            up = datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())
            h = int(up.total_seconds() // 3600)
            m = int((up.total_seconds() % 3600) // 60)
            d["up"] = f"UP:   {h}s {m}d"

            # GPU ve sicaklik (OpenHardwareMonitor acik degilse N/A kalir)
            d["temp"] = "TEMP: N/A"
            d["gpu"] = "GPU:  N/A"
            try:
                import pythoncom
                pythoncom.CoInitialize()   # COM her thread'de ayri baslatilmali
                try:
                    w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                    for s in w.Sensor():
                        if s.SensorType == "Temperature" and "CPU" in s.Name:
                            d["temp"] = f"TEMP: {s.Value:.0f}°C"
                        if s.SensorType == "Load" and "GPU" in s.Name:
                            d["gpu"] = f"GPU:  {s.Value:.0f}%"
                finally:
                    pythoncom.CoUninitialize()
            except Exception:
                pass

            self.stats_ready.emit(d)
        except Exception as e:
            print("update_monitor hata:", e)

    # Ana thread'de calisir (sinyal ile tetiklenir)
    def _apply_stats(self, d):
        for key, lbl in [("cpu", self.lbl_cpu), ("ram", self.lbl_ram), ("disk", self.lbl_disk),
                         ("net", self.lbl_net), ("bat", self.lbl_bat), ("up", self.lbl_up),
                         ("temp", self.lbl_temp), ("gpu", self.lbl_gpu)]:
            if key in d:
                lbl.setText(d[key])

    # Ayri thread: sadece ag istegi yapar, sonucu sinyalle yollar.
    def check_remote_status(self):
        ok = False
        try:
            r = requests.get("http://localhost:5000/", timeout=2)
            ok = (r.status_code == 200)
        except Exception:
            ok = False
        self.remote_ready.emit(ok)

    def _apply_remote(self, ok):
        if ok:
            self.lbl_remote.setText("REMOTE: ONLINE")
            self.lbl_remote.setStyleSheet("color: #00ff88; font-family: 'Courier New'; font-size: 10px;")
        else:
            self.lbl_remote.setText("REMOTE: OFFLINE")
            self.lbl_remote.setStyleSheet("color: #ff4444; font-family: 'Courier New'; font-size: 10px;")

    def show_qr(self):
        try:
            import io
            import qrcode
            from PyQt5.QtGui import QImage
            from PyQt5.QtWidgets import QDialog
            with open(r"C:\Jarvis\jarvis_url.txt", "r", encoding="utf-8") as f:
                url = f.read().strip()
            if not url:
                raise ValueError("jarvis_url.txt bos")
            qr = qrcode.make(url)
            qr_dialog = QDialog(self)
            qr_dialog.setWindowTitle("JARVIS QR")
            qr_dialog.setStyleSheet("background: black;")
            lay = QVBoxLayout(qr_dialog)
            lbl = QLabel()
            buf = io.BytesIO()
            qr.save(buf, format="PNG")
            buf.seek(0)
            img = QImage.fromData(buf.read())
            lbl.setPixmap(QPixmap.fromImage(img).scaled(200, 200))
            lay.addWidget(lbl)
            qr_dialog.exec_()
        except Exception as e:
            print("QR hata:", e)
            traceback.print_exc()
            signals.set_text.emit("QR HATA")

    def show_dashboard(self):
        try:
            from dashboard import DashboardWindow
            if not hasattr(self, '_dashboard'):
                self._dashboard = DashboardWindow()
            self._dashboard.show()
            self._dashboard.raise_()
        except Exception as e:
            print("Dashboard hata:", e)
            traceback.print_exc()
            signals.set_text.emit("DASHBOARD HATA")


# ── Tray ──
def make_tray_icon():
    px = QPixmap(32, 32)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(0, 180, 255), 2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(2, 2, 28, 28)
    p.setPen(QColor(0, 180, 255))
    p.setFont(QFont("Courier New", 7, QFont.Bold))
    p.drawText(0, 0, 32, 32, Qt.AlignCenter, "J")
    p.end()
    return QIcon(px)


# ── Speak ──
def play_music_queue():
    global music_playing
    music_dir = r"C:\Users\ASUS\Music"
    songs = [os.path.join(music_dir, f) for f in os.listdir(music_dir)
             if f.endswith(('.mp3', '.wav', '.m4a'))]
    random.shuffle(songs)
    media_list = vlc_instance.media_list_new(songs)
    vlc_player.set_media_list(media_list)
    vlc_player.play()
    vlc_player.set_playback_mode(vlc.PlaybackMode.loop)
    music_playing = True

def stop_music():
    global music_playing
    music_playing = False
    vlc_player.stop()

# ── Hazir cevaplarin esprili versiyonlari: her seferinde biri rastgele secilir ──
# Kapatmak icin ESPRILI_CEVAP = False yap. Yeni cevap eklemek icin listeye yaz.
ESPRILI_CEVAP = True
ESPRILI = {
    "Müzik çalıyorum.": ["Müzik geliyor. Komşular da dinlesin.", "Hemen. Sessizlik biraz fazla ciddiydi zaten.", "Müzik çalıyor. İyi bir seçim, her zamanki gibi."],
    "Müzik durduruldu.": ["Müzik durdu. Sessizliğin tadını çıkar.", "Tamamdır, sustu.", "Durdurdum. Kulaklar dinlensin."],
    "Sonraki şarkı.": ["Sıradaki geliyor.", "Bunu atladım, şüphesiz haklıydın.", "Sonraki şarkı. Umarım bu daha iyidir."],
    "Önceki şarkı.": ["Bir adım geri.", "Eskiye dönüyoruz, nostalji iyidir.", "Önceki şarkı, buyur."],
    "Müzik duraklatıldı.": ["Duraklattım, ben buradayım.", "Müzik beklemede.", "Tamam, nefes alalım."],
    "Müzik devam ediyor.": ["Devam ediyoruz.", "Kaldığımız yerden.", "Müzik geri döndü."],
    "Ses kapatıldı.": ["Ses kapandı. Mutlak sessizlik.", "Sessize aldım.", "Sus pus."],
    "Ses kısıldı.": ["Biraz kıstım.", "Kısıldı. Kulakların sağlığına.", "Daha mütevazı bir ses."],
    "Ses açıldı.": ["Açtım. Komşuları unutma.", "Ses yükseldi.", "Daha yüksek, buyur."],
    "Ekran görüntüsü alındı.": ["Ekran görüntüsü alındı. Belki bir delil olarak saklarız.", "Çektim, kanıt elimizde.", "Görüntü tamam."],
    "Bilgisayar kilitleniyor.": ["Kilitliyorum. Sırların güvende.", "Bilgisayar kilitleniyor, kimse bakmasın.", "Kilitlendi. Dönünce görüşürüz."],
    "YouTube açılıyor.": ["YouTube açılıyor. Sadece bir video, söz.", "YouTube geliyor, zaman kaybolmaya hazır.", "YouTube açılıyor."],
    "Google açılıyor.": ["Google açılıyor. Cevap orada, merak etme.", "Google'a gidiyoruz.", "Google açıldı."],
    "Claude açılıyor.": ["Claude açılıyor. Akıllı kardeşim.", "Claude geliyor.", "Claude açılıyor."],
    "Steam açılıyor.": ["Steam açılıyor. Ödevler sonra.", "Steam geliyor. Bugün sadece bir oyun, değil mi?", "Steam açılıyor."],
    "WhatsApp açılıyor.": ["WhatsApp açılıyor. Mesajlar bekliyor.", "WhatsApp geliyor.", "WhatsApp açılıyor."],
    "Not defteri açılıyor.": ["Not defteri açılıyor, büyük fikirler için.", "Not defteri hazır.", "Not defteri açılıyor."],
    "Kablosuz bağlantı açıldı.": ["Wi-Fi açıldı, dünyayla tekrar bağlandık.", "Bağlantı geri geldi.", "Kablosuz açıldı."],
    "Bluetooth açıldı.": ["Bluetooth açıldı, eşleşmeler başlasın.", "Bluetooth hazır.", "Bluetooth açıldı."],
    "Bluetooth kapatıldı.": ["Bluetooth kapandı.", "Bluetooth uykuya yattı.", "Bluetooth kapatıldı."],
    "Karanlık mod açıldı.": ["Karanlık mod. Gözlerin teşekkür eder.", "Işıkları kıstım.", "Karanlık moda geçtim."],
    "Aydınlık mod açıldı.": ["Aydınlık mod. Gözlerine dikkat.", "Işıklar açıldı.", "Aydınlık moda geçtim."],
    "Telefon bulma sayfası açılıyor.": ["Telefon bulma sayfası açılıyor. Yine mi kayıp?", "Telefonu arıyoruz, belki koltuğun arasındadır.", "Telefon bulma sayfası açılıyor."],
    "İptal edildi.": ["İptal edildi, vazgeçmek de bir karardır.", "Tamamdır, iptal.", "İptal edildi."],
    "Görüşürüz Zeynep.": ["Görüşürüz Zeynep, ben buradayım.", "Kendine iyi bak Zeynep.", "Görüşürüz Zeynep. Işıkları açık bırakıyorum."],
    "Üzgünüm Zeynep, bu komutu anlayamadım.": ["Üzgünüm Zeynep, bu komutu anlayamadım. Biraz daha net söyleyebilir misin?", "Üzgünüm Zeynep, tam yakalayamadım. Bir daha?", "Üzgünüm Zeynep, bunu anlayamadım."],
}


def _espri(text):
    if ESPRILI_CEVAP:
        secenekler = ESPRILI.get(text)
        if secenekler:
            return random.choice(secenekler)
    return text


def speak(text, voice=None):
    text = _espri(text)
    with speak_lock:
        konusma_dur.clear()
        _speak_basla_t[0] = time.time()
        is_speaking.set()   # mikrofonu sustur
        try:
            signals.set_status.emit("speaking")
            signals.set_text.emit(tr_upper(text)[:20])
            fx.beep("error" if any(k in text.lower() for k in ("üzgünüm", "sorry")) else "chime")
            try:
                import jarvis_server
                jarvis_server.broadcast_response(text)
            except Exception:
                pass
            def _basla():
                for cb in list(response_callbacks):
                    try:
                        cb(text)
                    except Exception:
                        pass
            fish_speak(text, voice, _basla)
            try:
                import jarvis_island
                jarvis_island.speech_done()   # ada, konusma bitince kapanmaya baslasin
            except Exception:
                pass
        except Exception as e:
            print("speak hata:", e)
        finally:
            is_speaking.clear()   # hata olsa bile mikrofon ve kilit serbest kalir
    signals.set_status.emit("listening")
    signals.set_text.emit("LISTENING...")
    try:
        import jarvis_server
        jarvis_server.broadcast_status("listening")
    except Exception:
        pass

def play_sound(file):
    threading.Thread(target=lambda: os.system(
        f'powershell -WindowStyle Hidden -c "Add-Type -AssemblyName presentationCore; '
        f'$m = New-Object System.Windows.Media.MediaPlayer; '
        f'$m.Open(\'{file}\'); $m.Play(); Start-Sleep 4"'
    ), daemon=True).start()

def system_status():
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    b = psutil.sensors_battery()
    metin = f"İşlemci yüzde {cpu:.0f}. Bellek yüzde {ram:.0f}."
    if b:
        metin += f" Pil yüzde {int(b.percent)}."
    speak(metin)

def weather():
    try:
        res = requests.get("https://wttr.in/?format=3&lang=tr", timeout=5)
        metin = re.sub(r"[^\w\s:+\-°.,]", "", res.text)        # emojileri temizle
        metin = re.sub(r"-(\d)", r"eksi \1", metin)             # -3 -> eksi 3
        metin = metin.replace("°C", " derece").replace("+", "")
        metin = re.sub(r"\s+", " ", metin).strip()              # emoji yerinde kalan bosluklari topla
        speak(metin or "Hava durumu bilgisine ulaşamadım.")
    except:
        speak("Hava durumu bilgisine ulaşamadım.")


# --- Saate gore selamlama ---
def get_greeting():
    saat = datetime.datetime.now().hour
    if 6 <= saat < 11:
        return "Günaydın dostum, güne nasıl başlıyoruz?"
    if 11 <= saat < 17:
        return "Selam dostum, gündüz vaktinde ne yapıyoruz?"
    if 17 <= saat < 22:
        return "Akşamın hayırlı olsun dostum"
    return "Bu saatte hâlâ ayakta mısın dostum? Uyusan iyi olur ama ben buradayım"


# ── Sabah özeti (günde bir kez) ──
SABAH_DOSYA = r"C:\Jarvis\sabah_son.txt"

def hava_metni():
    try:
        res = requests.get("https://wttr.in/?format=3&lang=tr", timeout=5)
        metin = re.sub(r"[^\w\s:+\-°.,]", "", res.text)
        metin = re.sub(r"-(\d)", r"eksi \1", metin)
        metin = metin.replace("°C", " derece").replace("+", "")
        return re.sub(r"\s+", " ", metin).strip()
    except Exception:
        return ""

def sabah_ozeti():
    bugun = datetime.date.today().isoformat()
    try:
        with open(SABAH_DOSYA, "r", encoding="utf-8") as f:
            if f.read().strip() == bugun:
                return   # bugün zaten söylendi
    except Exception:
        pass
    try:
        with open(SABAH_DOSYA, "w", encoding="utf-8") as f:
            f.write(bugun)
    except Exception as e:
        print("Sabah dosyası yazılamadı:", e)
    parcalar = [get_greeting(), f"Saat {datetime.datetime.now().strftime('%H:%M')}."]
    hava = hava_metni()
    if hava:
        parcalar.append(hava + ".")
    b = psutil.sensors_battery()
    if b:
        parcalar.append(f"Bilgisayarın pili yüzde {int(b.percent)}.")
    try:
        import jarvis_panels
        bekleyen = [x["text"] for x in jarvis_panels._tasks() if not x.get("done")]
        if bekleyen:
            ilk = ", ".join(bekleyen[:3])
            parcalar.append(f"{len(bekleyen)} bekleyen görevin var: {ilk}.")
    except Exception as e:
        print("Sabah ozeti gorev hata:", e)
    hat = _bugunku_hatirlatmalar()
    if hat:
        ilk = ", ".join(f"saat {at.strftime('%H:%M')}te {msg}" for at, msg in hat[:3])
        parcalar.append(f"Bugün için {len(hat)} hatırlatman var: {ilk}.")
    speak(" ".join(parcalar))

def wifi_toogle(enable):
    action = "enabled" if enable else "disabled"
    subprocess.run(
        ["netsh", "interface", "set", "interface", "Wi-Fi", f"admin={action}"],
        capture_output=True
    )

def bluetooth_toggle(enable):
    cmd = "Enable-PnpDevice" if enable else "Disable-PnpDevice"
    subprocess.run(["powershell", "-Command", f"Get-PnpDevice|Where-Object {{$_.FriendlyName -like '*Bluetooth*' -and $_.Class -eq 'Bluetooth'}} | {cmd} -Confirm:$false"], capture_output=True)

def dark_mode_toggle(dark):
    value = "0" if dark else "1"
    subprocess.run([
        "reg", "add", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "/v", "AppsUseLightTheme", "/t", "REG_DWORD", "/d", value, "/f"
    ], capture_output=True)
    subprocess.run([
        "reg", "add", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "/v", "SystemUsesLightTheme", "/t", "REG_DWORD", "/d", value, "/f"
    ], capture_output=True)



# --- Hatirlatma (yeniden baslatinca da kaybolmasin diye diske yazilir) ---
REMINDERS_FILE = r"C:\Jarvis\reminders.json"
_rem_lock = threading.Lock()


def _reminders_load():
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _reminders_save(items):
    try:
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Hatirlatma kaydedilemedi:", e)


def _reminder_remove(at_iso, message):
    with _rem_lock:
        items = [x for x in _reminders_load() if not (x.get("at") == at_iso and x.get("msg") == message)]
        _reminders_save(items)


def set_reminder(minutes, message):
    at = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    at_iso = at.isoformat(timespec="seconds")
    with _rem_lock:
        items = _reminders_load()
        items.append({"at": at_iso, "msg": message})
        _reminders_save(items)

    def _wait_and_remind():
        time.sleep(max(0.0, minutes * 60))
        speak(f"Hatırlatma: {message}")
        _reminder_remove(at_iso, message)
    threading.Thread(target=_wait_and_remind, daemon=True).start()


def _reminders_rearm():
    """JARVIS yeniden baslayinca: suresi gecmemis hatirlatmalari yeniden kurar. 15 dk'dan fazla gecikmis
    olanlar (bilgisayar kapaliyken suresi dolanlar) sessizce silinir, bir daha soylenmez."""
    now = datetime.datetime.now()
    for item in list(_reminders_load()):
        try:
            at = datetime.datetime.fromisoformat(item["at"])
        except Exception:
            _reminder_remove(item.get("at", ""), item.get("msg", ""))
            continue
        delay = (at - now).total_seconds()
        if delay > 0:
            def _wait(at_iso=item["at"], message=item["msg"], delay=delay):
                time.sleep(delay)
                speak(f"Hatırlatma: {message}")
                _reminder_remove(at_iso, message)
            threading.Thread(target=_wait, daemon=True).start()
        elif delay > -900:
            speak(f"Geciken hatırlatma: {item['msg']}")
            _reminder_remove(item["at"], item["msg"])
        else:
            _reminder_remove(item["at"], item["msg"])


def _bugunku_hatirlatmalar():
    """Sabah ozeti icin: bugune ait, henuz calismamis hatirlatmalarin kisa listesi."""
    bugun = datetime.date.today()
    saatli = []
    for item in _reminders_load():
        try:
            at = datetime.datetime.fromisoformat(item["at"])
        except Exception:
            continue
        if at.date() == bugun:
            saatli.append((at, item["msg"]))
    saatli.sort()
    return saatli

# ── El hareketleri (kamera) ──
_gesture = None


def _vlc_komut(cmd):
    """JARVIS'in kendi VLC listesine komut yollar."""
    try:
        mp = vlc_player.get_media_player()
        if cmd == "play":
            if not mp.is_playing():
                vlc_player.play()
        elif cmd == "pause":
            if mp.is_playing():
                vlc_player.pause()
        elif cmd == "next":
            vlc_player.next()
        elif cmd == "prev":
            vlc_player.previous()
    except Exception as e:
        print("VLC komutu hata:", e)


def _media_control(cmd):
    """Medya komutu: play / pause / next / prev (toggle degil, acik komut).
    Sira: 1) JARVIS'in kendi VLC'si su an caliyorsa ona, 2) Windows medya oturumuna (Spotify, YouTube Music,
    tarayici...), 3) oturum yoksa VLC listesine. Hem sesli komutlar hem el hareketleri bunu kullanir."""
    def run():
        try:
            if music_playing and vlc_player.get_media_player().is_playing():
                _vlc_komut(cmd)
                return
        except Exception:
            pass
        try:
            from winsdk.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as M

            async def go():
                s = (await M.request_async()).get_current_session()
                if not s:
                    return False
                if cmd == "play":
                    await s.try_play_async()
                elif cmd == "pause":
                    await s.try_pause_async()
                elif cmd == "next":
                    await s.try_skip_next_async()
                elif cmd == "prev":
                    await s.try_skip_previous_async()
                return True
            if asyncio.run(go()):
                print("Medya:", cmd, "-> Windows oturumuna gitti")
                return
            print("Medya:", cmd, "-> aktif Windows medya oturumu yok")
        except Exception as e:
            print("Medya komutu hata (pip install winsdk gerekebilir):", e)
        if music_playing:
            _vlc_komut(cmd)
    threading.Thread(target=run, daemon=True).start()


def _volume_step(up, steps=3):
    """Windows ses tusunu basar (her tus ~%2). Hizli: powershell acmaz."""
    try:
        import ctypes
        vk = 0xAF if up else 0xAE            # VK_VOLUME_UP / VK_VOLUME_DOWN
        for _ in range(steps):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
    except Exception as e:
        print("Ses tusu hata:", e)


_bright = {"v": None}
_bright_lock = threading.Lock()


def _brightness_step(delta):
    """Ekran parlakligini delta (+/- yuzde) kadar degistirir. Laptop ekrani icin: pip install screen-brightness-control"""
    def run():
        with _bright_lock:
            try:
                import screen_brightness_control as sbc
                if _bright["v"] is None:
                    cur = sbc.get_brightness()
                    _bright["v"] = int(cur[0] if isinstance(cur, (list, tuple)) else cur)
                nv = max(5, min(100, _bright["v"] + delta))
                sbc.set_brightness(nv)
                _bright["v"] = nv
            except Exception as e:
                _bright["v"] = None
                print("Parlaklik hata (pip install screen-brightness-control gerekebilir):", e)
    threading.Thread(target=run, daemon=True).start()


SCRCPY_DIR = r"C:\Jarvis\scrcpy"           # scrcpy.exe'yi buraya cikar (https://github.com/Genymobile/scrcpy)
_phone_proc = {"p": None}
PHONE_PIN_FILE = r"C:\Jarvis\phone_pin.txt"     # telefon PIN'in BU dosyaya duz metin olarak yazilir (kendi telefonun icin)


def _adb(args, timeout=8):
    exe = os.path.join(SCRCPY_DIR, "adb.exe")
    if not os.path.isfile(exe):
        return None
    try:
        return subprocess.run([exe] + args, capture_output=True, timeout=timeout)
    except Exception as e:
        print("adb hata:", e)
        return None


def _telefon_kilidini_ac():
    """Telefonu uyandirir, kilit ekranini kaydirir ve C:\\Jarvis\\phone_pin.txt icindeki PIN'i yazar.
    Cihaza gore kilit ekrani farkli davranabilir (ornegin yukari kaydirma gerekmeyebilir), bu durumda
    jarvis_voice.py icindeki bu fonksiyonu kendi telefonuna gore ayarlaman gerekebilir."""
    try:
        with open(PHONE_PIN_FILE, "r", encoding="utf-8") as f:
            pin = f.read().strip()
    except Exception:
        return False
    if not pin or not pin.isdigit():
        print("Telefon PIN dosyasi yok ya da gecersiz:", PHONE_PIN_FILE)
        return False
    _adb(["shell", "input", "keyevent", "224"])                         # ekrani uyandir
    time.sleep(0.5)
    _adb(["shell", "input", "swipe", "540", "1600", "540", "900"])      # kilit ekranini yukari kaydir
    time.sleep(0.5)
    _adb(["shell", "input", "text", pin])                               # PIN'i yaz
    time.sleep(0.2)
    _adb(["shell", "input", "keyevent", "66"])                          # Enter
    return True




def _telefonu_goster():
    """scrcpy ile telefon ekranini bilgisayarda acar. Kablosuz icin once bir kez 'adb pair' / 'adb connect'
    ile eslestirme gerekir (JARVIS bunu yapmaz, elle bir kerelik kurulum)."""
    exe = os.path.join(SCRCPY_DIR, "scrcpy.exe")
    if not os.path.isfile(exe):
        speak("scrcpy kurulu değil. Scrcpy'yi indirip C colon Jarvis scrcpy klasörüne çıkar.")
        return
    p = _phone_proc["p"]
    if p is not None and p.poll() is None:
        speak("Telefon ekranı zaten açık.")
        return
    try:
        _phone_proc["p"] = subprocess.Popen([exe, "--window-title=JARVIS - Telefon", "--max-size=800"],
                                            cwd=SCRCPY_DIR)
        speak("Telefon ekranı açılıyor.")
        if os.path.isfile(PHONE_PIN_FILE):
            threading.Timer(1.5, _telefon_kilidini_ac).start()          # pencere acilsin diye kisa bekleme
    except Exception as e:
        print("scrcpy hata:", e)
        speak("Telefon ekranını açamadım. Telefon bağlı ve USB hata ayıklama açık mı?")


def _volume_mute():
    """Sessize al / sesi geri ac (Windows ses kapatma tusu, her basista degisir)."""
    try:
        import ctypes
        ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)     # VK_VOLUME_MUTE
        ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
    except Exception as e:
        print("Sessize alma hata:", e)


def _ekran_goruntusu_al():
    """Ekran goruntusunu C:\\Jarvis icine kaydeder. Basariliysa dosya adini, degilse None doner."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        fname = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img.save(os.path.join(r"C:\Jarvis", fname))
        return fname
    except Exception as e:
        print("Ekran goruntusu hata:", e)
        return None


def _gesture_actions():
    acts = {n: (lambda n=n: _media_control(n)) for n in ("play", "pause", "next", "prev")}
    acts["vol_up"] = lambda: _volume_step(True)
    acts["vol_down"] = lambda: _volume_step(False)
    acts["screenshot"] = _ekran_goruntusu_al
    acts["describe"] = lambda: threading.Thread(target=_ekrani_acikla, args=("bu ne",), daemon=True).start()
    acts["mute"] = _volume_mute
    acts["bright_up"] = lambda: _brightness_step(5)
    acts["bright_down"] = lambda: _brightness_step(-5)
    acts["wake"] = _el_ile_uyandir
    acts["lock"] = _el_ile_kilitle
    acts["world_in"] = lambda: _world_zoom(True)
    acts["world_out"] = lambda: _world_zoom(False)
    acts["world_exit"] = _world_zoom_bitti
    return acts


def _gesture_feedback(name):
    # hareket algilaninca adada kisa yazi ("Durduruldu", "Sonraki sarki"...)
    try:
        import jarvis_gesture
        import jarvis_island
        jarvis_island.react(name, jarvis_gesture.LABELS.get(name, name))
    except Exception:
        pass


def _gesture_frame(data, w, h, info):
    # kamera karesi -> adadaki canli onizleme penceresi
    try:
        import jarvis_island
        jarvis_island.push_frame(data, w, h, info)
    except Exception:
        pass


def _gesture_ui(on):
    """Ada gostergesi + yuzdeki el dugmesi + kamera penceresi: hepsini el modunun durumuna esitler."""
    try:
        import jarvis_island
        jarvis_island.set_gesture(on)
        if not on:
            jarvis_island.show_camera(False)
    except Exception:
        pass
    try:
        window.hand_state.emit(bool(on))
    except Exception:
        pass


def _gesture_stopped(reason):
    # kamera kesildi / hata: el modu kendiliginden kapandi
    _gesture_ui(False)
    speak(reason)


def _gesture_kontrolcu():
    global _gesture
    import jarvis_gesture
    if _gesture is None:
        _gesture = jarvis_gesture.GestureController(
            actions=_gesture_actions(), on_event=_gesture_feedback,
            on_stop=_gesture_stopped, on_frame=_gesture_frame)
    return _gesture


def _gesture_preview(on):
    """Kamera penceresi kapaninca (X) sadece onizleme durur, el modu acik kalir."""
    if _gesture is not None:
        _gesture.preview = bool(on)


def _gesture_ac(preview=False):
    ctrl = _gesture_kontrolcu()
    was_running = ctrl.running
    ctrl.preview = bool(preview)
    ok, msg = ctrl.start(say=speak)
    if ok:
        _gesture_ui(True)
        if preview:
            try:
                import jarvis_island
                jarvis_island.show_camera(True)
            except Exception:
                pass
        if not was_running:
            b = psutil.sensors_battery()
            if b and not b.power_plugged:
                msg += " Pildesin, bilgisayar biraz yorulabilir."
    return ok, msg


def _gesture_kapat():
    _world_zoom_bitti()
    if _gesture is not None and _gesture.running:
        _gesture.stop()
        _gesture_ui(False)
        return True
    _gesture_ui(False)
    return False


def _gesture_toggle():
    """Yuzdeki / adadaki el dugmesi: kapaliysa kamera penceresiyle birlikte acar, aciksa kapatir."""
    if _gesture is not None and _gesture.running:
        _gesture_kapat()
        speak("El modu kapatıldı.")
    else:
        ok, msg = _gesture_ac(preview=True)
        speak(msg)


def _gesture_komutu(komut):
    """'el modu ac' / 'el modu kapat' (ayrica 'hareket modu', 'jest modu'). Eslesmezse False doner.
    'el modu ac kamera' / 'el modu goster' dersen canli kamera penceresi de acilir."""
    if not re.search(r"\b(?:el|hareket|jest)\w* (?:modu|kontrol)\w*", komut):
        return False
    if re.search(r"\b(?:kapat|kapa|durdur|bitir|iptal)\w*", komut):
        if _gesture_kapat():
            speak("El modu kapatıldı.")
        else:
            speak("El modu zaten kapalı.")
        return True
    ok, msg = _gesture_ac(preview=bool(re.search(r"\b(?:kamera|goster|pencere|onizleme)\w*", komut)))
    speak(msg)
    return True


def _panel_komutu(komut, orijinal):
    # gorev / not / etkinlik komutlari (jarvis_panels.py). Eslesmezse False doner.
    try:
        import jarvis_panels
        return jarvis_panels.handle(komut, orijinal, speak)
    except Exception as e:
        print("Panel komutu hata:", e)
        return False


# ── Komut işleme (hem ses hem yazı için) ──
active = False
ANTHROPIC_MODEL = "claude-sonnet-5-5"    # ekrani aciklayan model (daha ucuz/hizli istersen: "claude-haiku-5-5")


def _anthropic_key():
    """API anahtari: ANTHROPIC_API_KEY ortam degiskeni ya da C:\\Jarvis\\anthropic_key.txt dosyasi."""
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not k:
        try:
            with open(os.path.join(r"C:\Jarvis", "anthropic_key.txt"), "r", encoding="utf-8") as f:
                k = f.read().strip()
        except Exception:
            pass
    return k


def _ekrani_acikla(komut=""):
    """'Bu ne?' / 'ekranda ne var': ekran goruntusunu alir, gorsel anlayan modele sorar, cevabi sesli okur.
    Goruntu diske YAZILMAZ; sadece komut verince cekilir ve Anthropic API'sine gonderilir."""
    key = _anthropic_key()
    if not key:
        speak("Ekranı açıklamak için bir Anthropic API anahtarı lazım. "
              "C:\\Jarvis klasörüne anthropic_key.txt adlı bir dosya açıp anahtarı içine yaz.")
        return
    speak("Ekrana bakıyorum.")
    try:
        import base64
        import io
        from PIL import ImageGrab
        img = ImageGrab.grab().convert("RGB")
        img.thumbnail((1568, 1568))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        soru = (f'Kullanıcı sesli olarak şunu dedi: "{komut}". '
                "Ekran görüntüsüne bakarak buna cevap ver. Soru belirsizse ekranda ne olduğunu kısaca açıkla.")
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 300,
                "system": ("Sesli asistan JARVIS'sin. Türkçe cevap ver, en fazla 3 kısa cümle. "
                           "Cevap yüksek sesle okunacak: markdown, madde işareti, emoji ve URL kullanma."),
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": soru}]}],
            },
            timeout=40)
        if r.status_code != 200:
            print("Ekran aciklama hata:", r.status_code, r.text[:300])
            speak("Açıklayamadım. API anahtarını ya da bağlantını kontrol et.")
            return
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        speak(text or "Ekranda bir şey seçemedim.")
    except Exception as e:
        print("Ekran aciklama hata:", e)
        speak("Ekranı açıklarken bir hata oldu.")


_hud_level = {"v": 0.0}
HUD_STEP = 0.12          # iki el hareketinde bir adimda HUD kac buyusun/kucusun (0..1 arasi)


def _world_zoom(step_in):
    """Iki eli birbirinden uzaklastir/yaklastir hareketi: holografik harita HUD'unu (jarvis_hud.py) buyutur/kucultur."""
    try:
        import jarvis_island
        _hud_level["v"] = max(0.0, min(1.0, _hud_level["v"] + (HUD_STEP if step_in else -HUD_STEP)))
        jarvis_island.hud_set_level(_hud_level["v"])
    except Exception as e:
        print("HUD hata:", e)


def _world_zoom_bitti():
    """Eller indirilince (world_exit): HUD yumusakca kapanir."""
    try:
        import jarvis_island
        _hud_level["v"] = 0.0
        jarvis_island.hud_close()
    except Exception as e:
        print("HUD kapatma hata:", e)


def _el_ile_uyandir():
    """El sallama hareketi: mikrofondan 'jarvis' demeden de JARVIS'i uyandirir (el modu acikken calisir)."""
    global active
    if active:
        return
    active = True
    fx.beep("wake")
    signals.show_ui.emit()
    signals.set_status.emit("listening")
    signals.set_text.emit("LISTENING...")
    speak(get_greeting())


def _el_ile_kilitle():
    """Avucu kameraya itme hareketi: bilgisayari kilitler."""
    speak("Bilgisayar kilitleniyor.")
    os.system("rundll32.exe user32.dll,LockWorkStation")


def process_command(komut):
    global active
    orijinal = komut.replace("İ", "i").lower().strip()   # Turkce harfli hali (AI ve hatirlatma mesaji icin)
    komut = normalize(orijinal)                          # eslestirme icin ASCII hali
    print("Komut:", komut)
    signals.set_heard.emit(komut[:20].upper())
    # onay bekleyen tehlikeli komut varsa once onu coz
    if _handle_pending(komut):
        return

    # Uyandırma
    if has(komut, "selam dostum", "jarvis", "hey jarvis", "dostum") and not active:
        active = True
        fx.beep("wake")
        signals.show_ui.emit()
        signals.set_status.emit("listening")
        signals.set_text.emit("LISTENING...")
        speak(get_greeting())   # saate gore selamlama
        # "jarvis, ekrani tara" gibi komutla birlikte uyandirdiysa: selamdan sonra komutu da calistir
        _wake = r"\b(?:hey|selam|jarvis|dostum)\b[\s,.!?]*"
        kalan = re.sub(_wake, "", komut).strip(" ,.!?")
        if len(kalan) < 3:
            return                                   # sadece "jarvis" dedi, komut yok
        komut = re.sub(r"\s+", " ", kalan)
        orijinal = re.sub(r"\s+", " ", re.sub(_wake, "", orijinal, flags=re.I)).strip(" ,.!?")
        print("Komut (uyandirmadan sonra):", komut)

    if not active:
        # Yazı ile gelirse direkt aktif et
        active = True
        fx.beep("wake")
        signals.show_ui.emit()

    if has(komut, "goodbye", "sagol dostum gorusuruz", "kapat jarvis"):
        speak("Görüşürüz Zeynep.")
        time.sleep(0.5)
        active = False
        signals.hide_ui.emit()
        signals.set_status.emit("idle")
        signals.set_text.emit("STANDBY")

    elif "dakika sonra" in komut and "hatirlat" in komut:
        match = re.search(r"(\d+)\s*dakika sonra", komut)
        if match:
            dakika = int(match.group(1))
            hm = re.search(r"hatirlat", komut)
            if hm.start() >= match.end():
                # "5 dakika sonra <mesaj> hatirlat"  veya  "5 dakika sonra hatirlat <mesaj>"
                mesaj = orijinal[match.end():hm.start()].strip()
                sonrasi_ek_mi = komut[hm.end():hm.end() + 1].isalpha()   # "hatirlatir misin" gibi ek
                if not mesaj and not sonrasi_ek_mi:
                    mesaj = orijinal[hm.end():].strip()
            else:
                # "hatirlat 5 dakika sonra <mesaj>"
                mesaj = orijinal[match.end():].strip()
            mesaj = mesaj or "Süre doldu"
            speak(f"Tamam, {dakika} dakika sonra hatırlatacağım.")
            set_reminder(dakika, mesaj)
        else:
            speak("Hatırlatma süresini anlayamadım.")

    elif _panel_komutu(komut, orijinal):
        pass   # gorev / not / etkinlik komutu islendi

    elif _gesture_komutu(komut):
        pass   # el modu ac / kapat

    elif has(komut, "youtube"):
        webbrowser.open("https://youtube.com"); speak("YouTube açılıyor.")

    elif has(komut, "google"):
        webbrowser.open("https://google.com"); speak("Google açılıyor.")

    elif has(komut, "claude"):
        webbrowser.open("https://claude.ai"); speak("Claude açılıyor.")

    elif has(komut, "steam"):
        os.startfile("steam://open/main"); speak("Steam açılıyor.")

    elif has(komut, "whatsapp"):
        webbrowser.open("https://web.whatsapp.com"); speak("WhatsApp açılıyor.")

    elif has(komut, "not defteri", "notepad"):
        os.system("notepad.exe"); speak("Not defteri açılıyor.")

    elif has(komut, "muzik cal", "play music"):
        stop_music()
        threading.Thread(target=play_music_queue, daemon=True).start()
        speak("Müzik çalıyorum.")

    elif has(komut, "muzigi kapat", "stop music"):
        stop_music()
        speak("Müzik durduruldu.")

    elif has(komut, "sonraki sarki", "next song", "sarki degistir"):
        _media_control("next")
        speak("Sonraki şarkı.")

    elif has(komut, "onceki sarki", "previous song"):
        _media_control("prev")
        speak("Önceki şarkı.")

    elif has(komut, "muzigi durdur", "pause music"):
        _media_control("pause")
        speak("Müzik duraklatıldı.")

    elif has(komut, "muzige devam", "resume music"):
        _media_control("play")
        speak("Müzik devam ediyor.")

    elif has(komut, "saat", "saati", "time"):
        speak(f"Saat şu an {datetime.datetime.now().strftime('%H:%M')}")

    elif has(komut, "durum", "durumu", "status", "sistem") and not has(komut, "hava", "weather", "pil", "pili", "battery"):
        system_status()

    elif has(komut, "hava", "weather"):
        weather()

    elif has(komut, "pil", "pili", "battery"):
        b = psutil.sensors_battery()
        speak(f"Pil yüzde {int(b.percent)}" if b else "Pil bilgisi alınamıyor.")

    elif re.search(r"\bbu ne(?:dir)?\b|\bekranda ne\b|\bekrana bak\b|\bekrani (?:acikla|oku)\b|\bbunu acikla\b", komut):
        threading.Thread(target=_ekrani_acikla, args=(komut,), daemon=True).start()

    elif re.search(r"\btelefon\w* (?:goster|ac|baglan)\w*|\btelefon ekran\w*", komut):
        threading.Thread(target=_telefonu_goster, daemon=True).start()

    elif has(komut, "ekran goruntusu", "screenshot"):
        if _ekran_goruntusu_al():
            speak("Ekran görüntüsü alındı.")
        else:
            subprocess.run(["powershell", "-c",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.SendKeys]::SendWait('%{PRTSC}')"])
            speak("Ekran görüntüsü alındı.")

    elif has(komut, "sesi kapat", "mute"):
        subprocess.run(["powershell", "-c",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"])
        speak("Ses kapatıldı.")

    elif has(komut, "sesi kis", "volume down"):
        subprocess.run(["powershell", "-c",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"])
        speak("Ses kısıldı.")

    elif has(komut, "sesi ac", "volume up"):
        subprocess.run(["powershell", "-c",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"])
        speak("Ses açıldı.")

    elif re.search(r"\bharita\w*\b.*\bkapat\w*\b|\bharitayi kapat\w*\b", komut):
        _world_zoom_bitti()
        speak("Harita kapatıldı.")

    elif has(komut, "kilitle", "lock"):
        speak("Bilgisayar kilitleniyor.")
        os.system("rundll32.exe user32.dll,LockWorkStation")

    elif has(komut, "bilgisayari kapat", "shut down"):
        ask_confirmation("Bilgisayarı kapatmak üzereyim.", _do_shutdown)

    elif has(komut, "takvime ekle", "calendar"):
        webbrowser.open("https://calendar.google.com")
        speak("Google Takvim açılıyor.")

    elif has(komut, "ses", "sesi", "volume"):
        sayi = [int(s) for s in re.findall(r"\d+", komut)]
        if not sayi:
            speak("Ses seviyesini bir sayıyla söyle, örneğin: ses 50.")
        else:
            deger = max(0, min(100, sayi[0]))
            adim = deger // 2   # her tus vurusu yaklasik %2
            try:
                yukari = f"1..{adim} | ForEach-Object {{ $w.SendKeys([char]175) }}" if adim > 0 else ""
                subprocess.run(["powershell", "-c",
                    "$w = New-Object -ComObject WScript.Shell; "
                    "1..50 | ForEach-Object { $w.SendKeys([char]174) }; " + yukari])
                speak(f"Ses seviyesi {deger} olarak ayarlandı.")
            except Exception:
                speak("Ses ayarlanamadı.")

    elif has(komut, "parlaklik", "brightness"):
        sayi = [int(s) for s in re.findall(r"\d+", komut)]
        if not sayi:
            speak("Parlaklık seviyesini bir sayıyla söyle, örneğin: parlaklık 70.")
        else:
            deger = max(0, min(100, sayi[0]))
            try:
                subprocess.run(["powershell", "-c",
                    f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{deger})"])
                speak(f"Parlaklık {deger} olarak ayarlandı.")
            except Exception:
                speak("Parlaklık ayarlanamadı.")

    elif has(komut, "her seyi kapat", "close everything", "hepsini kapat"):
        ask_confirmation("Tüm uygulamaları kapatmak üzereyim.", _do_close_everything)

    elif has(komut, "wifi ac", "wifi aç", "wifi on"):
        wifi_toogle(True)
        speak("Kablosuz bağlantı açıldı.")

    elif has(komut, "wifi kapat", "wifi off"):
        ask_confirmation("Kablosuz bağlantıyı kapatmak üzereyim. Uzaktan erişim kesilecek.", _do_wifi_off)

    elif has(komut, "bluetooth ac", "bluetooth aç", "bluetooth on"):
        bluetooth_toggle(True)
        speak("Bluetooth açıldı.")

    elif has(komut, "bluetooth kapat", "bluetooth off"):
        bluetooth_toggle(False)
        speak("Bluetooth kapatıldı.")

    elif has(komut, "karanlik mod", "karanlık mod", "dark mode") and "kapat" not in komut:
        dark_mode_toggle(True)
        speak("Karanlık mod açıldı.")

    elif has(komut, "aydinlik mod", "aydınlık mod", "light mode", "karanlik modu kapat"):
        dark_mode_toggle(False)
        speak("Aydınlık mod açıldı.")

    elif has(komut,"telefonumu bul", "find my phone"):
        subprocess.Popen([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--profile-directory=Default",
            "https://www.google.com/android/find"
        ])
        speak("Telefon bulma sayfası açılıyor.")

    elif re.search(r"\bekrani tara|\bhedef\w*|\btarama yap|^tara$", komut):
        import jarvis_target
        threading.Thread(target=jarvis_target.tara, args=(komut, speak, _anthropic_key(), ANTHROPIC_MODEL), daemon=True).start()

    else:
        # Hicbir komut eslesmedigi zaman yapay zekaya (Claude API) sorulur.
        try:
            import jarvis_brain
            _t_ai = time.time()
            _cevap_no["n"] += 1
            _no = _cevap_no["n"]
            soru = orijinal
            if YARIM_BIRLESTIR and _bekleyen["metin"] and time.time() - _bekleyen["t"] < 10:
                soru = _bekleyen["metin"] + " " + orijinal    # yarim kalan cumleyi tamamla
                print("Yarim cumle birlestirildi:", soru)
            _bekleyen["metin"], _bekleyen["t"] = soru, time.time()
            cevap = jarvis_brain.ask_jarvis_ai(soru)
            print(f"[SURE] Yapay zeka cevabi: {time.time() - _t_ai:.1f} sn ({len(cevap)} karakter)")
            if _cevap_no["n"] != _no:
                print("Eski cevap iptal edildi (yeni soru geldi).")
                return
            speak(cevap)   # AI cevabi da varsayilan Turkce sesle okunur
            if not konusma_dur.is_set():
                _bekleyen["metin"] = ""            # tam okundu, birlestirmeye gerek yok
        except Exception as e:
            print("AI baglantisi hatasi:", e)
            speak("Üzgünüm Zeynep, bu komutu anlayamadım.")


# ── El çırpma algılama (aynı mikrofon akışı, ses dalgası widget'ını da besler) ──
def detect_clap():
    CHUNK = 1024
    RATE = 44100
    THRESHOLD = 3000
    CLAP_INTERVAL = 0.6
    COOLDOWN = 2.0

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

    print("El çırpma algılama aktif...")
    last_clap = 0
    clap_count = 0
    last_trigger = 0
    barge_chunks = 0

    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            volume = np.max(np.abs(audio_data))

            # gercek mikrofon seviyesini ses dalgasi widget'ina gonder
            level = min(1.0, float(volume) / 9000.0)
            fx.effect_signals.voice_level.emit(level)

            # araya girme: JARVIS konusurken sen yuksek sesle konusursan susar
            if BARGE_IN and is_speaking.is_set() and time.time() - _speak_basla_t[0] > 0.8:
                if level >= BARGE_SEVIYE:
                    barge_chunks += 1
                    if barge_chunks * CHUNK / RATE >= BARGE_SURE and not konusma_dur.is_set():
                        print("Araya girildi: JARVIS susturuldu.")
                        konusma_dur.set()
                else:
                    barge_chunks = 0
            else:
                barge_chunks = 0

            if volume > THRESHOLD and not is_speaking.is_set():
                now = time.time()
                if now - last_trigger > COOLDOWN:
                    if now - last_clap < CLAP_INTERVAL:
                        clap_count += 1
                        if clap_count >= 2:
                            print("El çırpma algılandı!")
                            clap_detected_event.set()
                            last_trigger = now
                            clap_count = 0
                    else:
                        clap_count = 1
                    last_clap = now
        except:
            pass

clap_detected_event = threading.Event()


# ── Voice Loop ──
def voice_loop():
    global active
    reco = sr.Recognizer()
    reco.energy_threshold = 400 if not music_playing else 900
    reco.dynamic_energy_threshold = False
    reco.pause_threshold = 1.3        # cumle arasi kisa duraklamada "bitti" sanma (varsayilan 0.8)

    while True:
        try:
            if is_speaking.is_set():
                time.sleep(0.15)
                continue
            if not active:
                clap_detected_event.wait(timeout=0.1)
                if clap_detected_event.is_set():
                    clap_detected_event.clear()
                    active = True
                    fx.beep("wake")
                    signals.show_ui.emit()
                    signals.set_status.emit("listening")
                    signals.set_text.emit("LISTENING...")
                    speak(get_greeting())
                continue

            with sr.Microphone() as source:
                reco.adjust_for_ambient_noise(source, duration=0.1)
                signals.set_text.emit("LISTENING...")
                try:
                    audio = reco.listen(source, timeout=6, phrase_time_limit=15)
                except sr.WaitTimeoutError:
                    continue

            if is_speaking.is_set():
                continue  # JARVIS tam o sirada konusmaya basladi, bu sesi at

            try:
                komut = reco.recognize_google(audio, language="tr-TR").lower()
            except:
                try:
                    komut = reco.recognize_google(audio, language="en-US").lower()
                except:
                    continue

            if len(komut.strip()) >= 3:
                threading.Thread(target=process_command, args=(komut,), daemon=True).start()

        except Exception as e:
            print("Hata:", e)
            pass

def _island_music_title_vlc():
    try:
        if not music_playing: return None
        mp = vlc_player.get_media_player()
        m = mp.get_media()
        if m is None: return None
        from urllib.parse import unquote
        return os.path.splitext(os.path.basename(unquote(m.get_mrl())))[0]
    except Exception:
        return None

def _island_media_info():
    """Ada icin: calan sarkinin adi, sanatcisi, konumu ve suresi (saniye). Yoksa None.
    Once Windows medya oturumu (Spotify, tarayici...), yoksa kendi VLC calarimiz."""
    try:
        import asyncio
        import datetime as _dt
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

        async def _get():
            mgr = await M.request_async()
            s = mgr.get_current_session()
            if not s:
                return None
            info = await s.try_get_media_properties_async()
            title = info.title or ""
            if not title:
                return None
            playing = s.get_playback_info().playback_status == 4   # 4 = caliyor
            pos = dur = 0.0
            try:
                tl = s.get_timeline_properties()
                start = tl.start_time.total_seconds()
                dur = max(0.0, tl.end_time.total_seconds() - start)
                pos = tl.position.total_seconds() - start
                if playing:
                    try:   # son guncellemeden bu yana gecen sureyi ekle
                        pos += (_dt.datetime.now(_dt.timezone.utc) - tl.last_updated_time).total_seconds()
                    except Exception:
                        pass
            except Exception:
                pass
            return {"title": title, "artist": info.artist or "",
                    "position": max(0.0, pos), "duration": dur, "playing": playing}

        r = asyncio.run(_get())
        if r:
            return r
    except Exception:
        pass
    try:   # yedek: kendi VLC muzik listemiz
        if music_playing:
            mp = vlc_player.get_media_player()
            title = _island_music_title_vlc()
            if title:
                return {"title": title, "artist": "",
                        "position": max(0, mp.get_time()) / 1000.0,
                        "duration": max(0, mp.get_length()) / 1000.0,
                        "playing": bool(mp.is_playing())}
    except Exception:
        pass
    return None


def _island_music_title():
    try:
        import asyncio
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
        async def _get():
            mgr = await M.request_async()
            s = mgr.get_current_session()
            if not s:
                return None
            if s.get_playback_info().playback_status != 4:  # 4 = çalıyor
                return None
            info = await s.try_get_media_properties_async()
            return f"{info.title} - {info.artist}" if info.artist else info.title
        t = asyncio.run(_get())
        if t:
            return t
    except Exception:
        pass
    return _island_music_title_vlc()
    


def _launch_main():
    """Boot animasyonu bittikten sonra asil JARVIS penceresini ve arka plan
    threadlerini baslatir."""
    global window
    window = JarvisWindow()

    # Yazi ile gelen komutlari isle
    signals.process_text.connect(lambda text: threading.Thread(
        target=process_command, args=(text,), daemon=True
    ).start())

    tray = QSystemTrayIcon(make_tray_icon(), app)
    menu = QMenu()
    qa = QAction("Çıkış")
    qa.triggered.connect(lambda: window.quit_all())
    menu.addAction(qa)
    tray.setContextMenu(menu)
    tray.setToolTip("J.A.R.V.I.S. - Dinliyor...")
    tray.show()
    globals()['_tray'] = tray  # referansi canli tut (cop toplayiciya kaptirma)

    import jarvis_server
    # threading.Thread: fonksiyonu arka planda calistirir, JARVIS donmaz.
    # daemon=True: ana program kapaninca thread de otomatik sonlanir.
    threading.Thread(target=jarvis_server.start_server, daemon=True).start()

    threading.Thread(target=detect_clap, daemon=True).start()
    threading.Thread(target=voice_loop, daemon=True).start()
    threading.Thread(target=_edge_isinma_dongusu, daemon=True).start()   # Ava'yi sicak tut

    if 6 <= datetime.datetime.now().hour < 11:
        threading.Timer(10, sabah_ozeti).start()
        threading.Timer(3, _reminders_rearm).start()

    try:
        import jarvis_island
        globals()['_island'] = jarvis_island.attach(
            music_getter=_island_music_title,
            media_getter=_island_media_info,
            gesture_toggle=_gesture_toggle,
            preview_cb=_gesture_preview,
            phone_cb=_telefonu_goster,
            response_callbacks=response_callbacks,
            effect_signals=fx.effect_signals)
    except Exception as e:
        print("Island hata:", e)
        traceback.print_exc()


def _hata_yakala(t, v, tb):
    # Yakalanmamis hata PyQt5'i sessizce kapatmasin: konsola ve dosyaya yaz.
    traceback.print_exception(t, v, tb)
    try:
        with open(r"C:\Jarvis\hata_log.txt", "a", encoding="utf-8") as f:
            f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            traceback.print_exception(t, v, tb, file=f)
            f.write("\n")
    except Exception:
        pass


if __name__ == "__main__":
    sys.excepthook = _hata_yakala
    kill_previous_instances()
    time.sleep(1.5)   # eski "Jarvis" yuzunun kapanmasi icin kisa bekleme (cakismayi onler)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    app.setQuitOnLastWindowClosed(False)

    # once acilis (boot) animasyonunu goster, bitince JARVIS'i baslat
    try:
        import jarvis_boot
        _splash = jarvis_boot.BootSplash(on_finish=_launch_main)
    except Exception as _e:
        print("Yeni açılış animasyonu yüklenemedi:", _e)
        _splash = fx.BootSplash(on_finish=_launch_main)
    _splash.show()

    sys.exit(app.exec_())