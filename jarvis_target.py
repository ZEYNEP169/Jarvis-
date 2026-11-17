# -*- coding: utf-8 -*-
"""
JARVIS HEDEF KILIDI: Iron Man tarzi ekran taramasi
====================================================
"Ekrani tara" / "hedef" dediginde: ekran goruntusu alinir, yapay zeka ekrandaki onemli seyleri bulur,
ekranin ustune (fare tiklamalarini engellemeden) taramali, kilitlenen hedef cerceveleri cizilir
ve JARVIS ne gordugunu sesli soyler.

jarvis_voice.py icinden kullanim (tek satirlik cagri, ayrintisi cevapta):
    import jarvis_target
    threading.Thread(target=jarvis_target.tara, args=(komut, speak, _anthropic_key(), ANTHROPIC_MODEL), daemon=True).start()

GIZLILIK: Ekran goruntusu diske YAZILMAZ, sadece komut verince cekilir ve Anthropic API'sine gonderilir.
API anahtari bu dosyada YOK: jarvis_voice.py'deki _anthropic_key() verir (ortam degiskeni ya da anthropic_key.txt).
"""

import base64
import io
import json
import math
import re
import time

import requests

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QObject, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QLinearGradient
from PyQt5.QtWidgets import QWidget, QApplication

# ── Ayarlar ──
MAX_HEDEF = 5               # en fazla kac hedef cizilsin
GOSTER_SURE = 7.0           # sonuc ekranda kac saniye kalsin
TARAMA_SURESI = 1.4         # tarama cubugunun ekrani yukaridan asagiya (ya da tersi) bir kez gecme suresi (sn); kucuk = hizli
MIN_TARAMA = 2.8            # sonuc cok hizli gelse bile en az bu kadar sn tarama animasyonu gorunsun
BEKLEME_MAX = 30.0          # cevap gelmezse tarama bu kadar saniye sonra kendiliginden kapanir
CYAN = QColor(70, 220, 255)
CYAN_LIGHT = QColor(210, 247, 255)
AMBER = QColor(255, 190, 70)

_bridge = None
_overlay = None


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


class _Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._targets = []
        self._t_start = time.monotonic()
        self._t_result = None
        self._fade = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def begin(self):
        sc = QApplication.primaryScreen().geometry()          # ImageGrab ana ekrani alir, ayni alan
        self.setGeometry(sc)
        self._targets = []
        self._t_start = time.monotonic()
        self._t_result = None
        self._pending = None
        self._fade = 1.0
        self.show()
        self._timer.start(16)

    def result(self, targets):
        self._pending = targets[:MAX_HEDEF]          # animasyon yeterince surunce gosterilir (_tick)

    def end(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        now = time.monotonic()
        if self._pending is not None and now - self._t_start >= MIN_TARAMA:
            self._targets = self._pending
            self._pending = None
            self._t_result = now
        if self._t_result is None:
            if now - self._t_start > BEKLEME_MAX:
                self.end()
                return
        else:
            left = GOSTER_SURE - (now - self._t_result)
            self._fade = max(0.0, min(1.0, left / 0.6))
            if left <= 0:
                self.end()
                return
        self.update()

    def paintEvent(self, _):
        try:
            self._paint()
        except Exception as e:
            print("Hedef cizim hatasi:", e)

    def _paint(self):
        W, H = self.width(), self.height()
        now = time.monotonic()
        f = self._fade
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        def col(c, a):
            return QColor(c.red(), c.green(), c.blue(), max(0, min(255, int(a * f))))

        # hafif mavi ton (ekrani karartmadan "tarama" hissi)
        p.fillRect(0, 0, W, H, QColor(10, 60, 90, int(26 * f)))

        # ── tarama cubugu: sonuc gelene kadar ekranda surekli YUKARI-ASAGI gider ──
        t = now - self._t_start
        if self._t_result is None:
            # ince yatay izgara (dijital tarama hissi)
            p.setPen(QPen(col(CYAN, 16), 1))
            for gy in range(0, H, 36):
                p.drawLine(QPointF(0, gy), QPointF(W, gy))
            ph = (t / TARAMA_SURESI) % 2.0                       # 0..1 asagi, 1..2 yukari
            going_down = ph <= 1.0
            u = ph if going_down else 2.0 - ph
            u = u * u * (3 - 2 * u) * 0.6 + u * 0.4              # uclarda hafif yavaslar, ortada hizli
            y = 6 + u * (H - 12)
            tail = 220.0                                         # hareketin arkasinda kalan parlak iz
            y0, y1 = (y - tail, y) if going_down else (y, y + tail)
            g = QLinearGradient(0, y0, 0, y1)
            if going_down:
                g.setColorAt(0.0, col(CYAN, 0))
                g.setColorAt(1.0, col(CYAN, 85))
            else:
                g.setColorAt(0.0, col(CYAN, 85))
                g.setColorAt(1.0, col(CYAN, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(0, y0, W, tail))
            # parlayan cubuk
            p.setPen(QPen(col(CYAN, 70), 9))
            p.drawLine(QPointF(0, y), QPointF(W, y))
            p.setPen(QPen(col(CYAN_LIGHT, 245), 2.4))
            p.drawLine(QPointF(0, y), QPointF(W, y))
            # kenarlarda olcek cizgileri + Y degeri
            p.setPen(QPen(col(CYAN_LIGHT, 220), 2))
            for tx in range(0, W, 48):
                p.drawLine(QPointF(tx, y - 5), QPointF(tx, y + 5))
            rf = QFont("Consolas", 10)
            rf.setBold(True)
            p.setFont(rf)
            p.setPen(col(CYAN_LIGHT, 240))
            p.drawText(QRectF(10, y - 22, 140, 16), Qt.AlignLeft | Qt.AlignVCenter, "Y %04d" % int(y))
            p.drawText(QRectF(W - 150, y - 22, 140, 16), Qt.AlignRight | Qt.AlignVCenter,
                       "%s" % ("▼ TARAMA" if going_down else "▲ TARAMA"))

        # ── ust baslik ──
        hf = QFont("Segoe UI", 13)
        hf.setBold(True)
        hf.setLetterSpacing(QFont.AbsoluteSpacing, 4.0)
        p.setFont(hf)
        p.setPen(col(CYAN_LIGHT, 240))
        if self._t_result is None:
            dots = "." * (int(t * 3) % 4)
            title = "J.A.R.V.I.S  //  EKRAN TARANIYOR" + dots
        else:
            title = "J.A.R.V.I.S  //  %d HEDEF KİLİTLENDİ" % len(self._targets)
        p.drawText(QRectF(0, 18, W, 30), Qt.AlignHCenter | Qt.AlignVCenter, title)
        p.setPen(QPen(col(CYAN, 120), 1.2))
        p.drawLine(QPointF(W * 0.35, 52), QPointF(W * 0.65, 52))

        # ── hedefler ──
        if self._t_result is not None:
            dt = now - self._t_result
            lf = QFont("Consolas", 11)
            lf.setBold(True)
            for i, tg in enumerate(self._targets):
                k = _ease((dt - i * 0.25) / 0.6)         # sirayla kilitlenir
                if k <= 0:
                    continue
                c = AMBER if i == 0 else CYAN
                x = tg["x"] * W
                y = tg["y"] * H
                w = max(46.0, tg["w"] * W)
                h = max(46.0, tg["h"] * H)
                e = (1 - k) * 70                           # disaridan ice daralan cerceve
                r = QRectF(x - e, y - e, w + 2 * e, h + 2 * e)
                L = max(14.0, min(34.0, min(w, h) / 3.0))
                p.setPen(QPen(col(c, 255 * k), 3.0))
                p.setBrush(Qt.NoBrush)
                for (cx, cy, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                                         (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
                    p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
                    p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * L))
                # ince ic cerceve
                p.setPen(QPen(col(c, 70 * k), 1.0, Qt.DashLine))
                p.drawRect(r)
                # nisangah
                mx, my = r.center().x(), r.center().y()
                p.setPen(QPen(col(c, 200 * k), 1.6))
                rr = 9 + 3 * math.sin(now * 5 + i)
                p.drawEllipse(QPointF(mx, my), rr, rr)
                for (ax, ay) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    p.drawLine(QPointF(mx + ax * (rr + 3), my + ay * (rr + 3)),
                               QPointF(mx + ax * (rr + 12), my + ay * (rr + 12)))
                # etiket
                if k > 0.7:
                    name = tg["ad"].upper()
                    p.setFont(lf)
                    tw = p.fontMetrics().horizontalAdvance("0%d  %s" % (i + 1, name)) + 24
                    bx = min(max(8.0, r.left()), W - tw - 8)
                    by = r.top() - 34 if r.top() > 60 else r.bottom() + 8
                    box = QRectF(bx, by, tw, 26)
                    p.setPen(QPen(col(c, 230), 1.4))
                    p.setBrush(QColor(4, 18, 30, int(205 * f)))
                    p.drawRect(box)
                    p.setPen(col(c, 255))
                    p.drawText(box, Qt.AlignCenter, "0%d  %s" % (i + 1, name))
        p.end()


class _Bridge(QObject):
    """Diger thread'lerden (ses dongusu) guvenle arayuz cagirmak icin."""
    sig_begin = pyqtSignal()
    sig_result = pyqtSignal(object)
    sig_end = pyqtSignal()

    def connect_all(self):
        """moveToThread'den SONRA cagrilir: yoksa slotlar ses thread'inde calisir ve animasyon (QTimer) hic islemez."""
        self.sig_begin.connect(self._begin)
        self.sig_result.connect(self._result)
        self.sig_end.connect(self._end)

    def _ov(self):
        global _overlay
        if _overlay is None:
            _overlay = _Overlay()
        return _overlay

    @pyqtSlot()
    def _begin(self):
        self._ov().begin()

    @pyqtSlot(object)
    def _result(self, targets):
        self._ov().result(targets)

    @pyqtSlot()
    def _end(self):
        self._ov().end()


def _get_bridge():
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
        app = QApplication.instance()
        if app is not None:
            _bridge.moveToThread(app.thread())         # slotlar her zaman ana (arayuz) thread'inde calissin
        _bridge.connect_all()
    return _bridge


def parse_targets(text):
    """Modelin cevabindan (JSON) ozet + hedef listesini cikarir. Bozuk cevaba dayanikli."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return text.strip(), []
    try:
        d = json.loads(m.group(0))
    except Exception:
        return "", []
    out = []
    for t in (d.get("hedefler") or []):
        try:
            x, y, w, h = (float(t[k]) for k in ("x", "y", "w", "h"))
            if w > 1.5 or h > 1.5 or x > 1.5 or y > 1.5:       # model 0-100 ya da piksel verdiyse gecersiz say
                continue
            x, y = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
            w, h = max(0.02, min(1.0 - x, w)), max(0.02, min(1.0 - y, h))
            out.append({"ad": str(t.get("ad", "hedef"))[:28], "x": x, "y": y, "w": w, "h": h})
        except Exception:
            continue
    return str(d.get("ozet", "")).strip(), out


def tara(komut, speak, api_key, model):
    """Ses komutuyla calisir (ayri thread'de cagir): ekrani tarar, hedefleri cizer, sonucu sesli soyler."""
    if not api_key:
        speak("Ekranı taramak için bir Anthropic API anahtarı lazım. "
              "C:\\Jarvis klasörüne anthropic_key.txt adlı bir dosya açıp anahtarı içine yaz.")
        return
    br = _get_bridge()
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab().convert("RGB")
        img.thumbnail((1568, 1568))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print("Hedef tarama ekran hatasi:", e)
        speak("Ekranın görüntüsünü alamadım.")
        return
    br.sig_begin.emit()
    speak("Taranıyor.")
    try:
        soru = ('Kullanıcı sesli olarak şunu dedi: "%s". Ekran görüntüsündeki EN FAZLA %d önemli şeyi (pencere, nesne, '
                'yazı, kişi, buton) hedef olarak seç. Kullanıcı belli bir şey istediyse onu birinci hedef yap. '
                'SADECE şu JSON ile cevap ver, başka hiçbir şey yazma: '
                '{"ozet": "en fazla 2 kısa Türkçe cümle", "hedefler": [{"ad": "en fazla 3 kelime", '
                '"x": sol_kenar, "y": ust_kenar, "w": genislik, "h": yukseklik}]}. '
                'x, y, w, h değerleri görüntünün genişliğine/yüksekliğine göre 0 ile 1 arasında ondalık sayıdır.'
                % (komut.replace('"', "'"), MAX_HEDEF))
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 700,
                  "system": "Sesli asistan JARVIS'in ekran tarama modülüsün. Sadece geçerli JSON döndürürsün.",
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                      {"type": "text", "text": soru}]}]},
            timeout=40)
        if r.status_code != 200:
            print("Hedef tarama API hatasi:", r.status_code, r.text[:300])
            br.sig_end.emit()
            speak("Tarayamadım. API anahtarını ya da bağlantını kontrol et.")
            return
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        ozet, hedefler = parse_targets(text)
        if hedefler:
            br.sig_result.emit(hedefler)
        else:
            br.sig_end.emit()
        speak(ozet or ("Ekranda belirgin bir hedef bulamadım." if not hedefler else "Hedefler kilitlendi."))
    except Exception as e:
        print("Hedef tarama hatasi:", type(e).__name__, e)
        br.sig_end.emit()
        speak("Tararken bir hata oldu.")