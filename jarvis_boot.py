# -*- coding: utf-8 -*-
"""
JARVIS ACILIS ANIMASYONU (Iron Man tarzi boot ekrani)
=====================================================
Jarvis baslarken ekranin ortasinda: genisleyen halkalar, parlayan arc reactor, sirayla "TAMAM" olan
sistem kontrol satirlari, ilerleme cubugu ve sonunda "J.A.R.V.I.S  CEVRIMICI" yazisi.
Bitince kendiliginden kapanir ve on_finish() cagrilir (JARVIS'in asil baslangici).

jarvis_voice.py'de (en altta, __main__ icinde) su satirin yerine:
    _splash = fx.BootSplash(on_finish=_launch_main)
sunu yaz:
    try:
        import jarvis_boot
        _splash = jarvis_boot.BootSplash(on_finish=_launch_main)
    except Exception as _e:
        print("Yeni acilis animasyonu yuklenemedi:", _e)
        _splash = fx.BootSplash(on_finish=_launch_main)

Not: satir "kontrolleri" gorseldir (gercek test yapmaz). CPU/RAM degerleri gercektir (psutil).
Internet, API anahtari ya da kisisel veri KULLANMAZ.
"""

import math
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QRadialGradient, QLinearGradient
from PyQt5.QtWidgets import QWidget, QApplication

try:
    import psutil
except Exception:
    psutil = None

# ── Ayarlar ──
BOOT_SURE = 5.2             # toplam animasyon suresi (sn)
W, H = 820, 520             # pencere boyu
CYAN = QColor(70, 220, 255)
CYAN_LIGHT = QColor(210, 247, 255)
AMBER = QColor(255, 190, 70)
CHECKS = [
    ("ÇEKİRDEK SİSTEMİ", 0.08), ("SES MODÜLÜ", 0.24), ("EL ALGILAMA", 0.40),
    ("DÜNYA AĞI", 0.56), ("YAPAY ZEKA BAĞLANTISI", 0.72), ("HEDEF KİLİDİ", 0.88),
]


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


class BootSplash(QWidget):
    def __init__(self, on_finish=None):
        super().__init__()
        self._on_finish = on_finish
        self._done = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(W, H)
        self._t0 = None
        self._cpu = 0
        self._ram = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def show(self):
        sc = QApplication.primaryScreen().availableGeometry()
        self.move(sc.center().x() - W // 2, sc.center().y() - H // 2)
        super().show()
        self._t0 = time.monotonic()
        self._timer.start(16)

    def _tick(self):
        if self._t0 is None:
            return
        t = time.monotonic() - self._t0
        if int(t * 4) % 2 == 0 and psutil is not None:
            try:
                self._cpu = int(psutil.cpu_percent(None))
                self._ram = int(psutil.virtual_memory().percent)
            except Exception:
                pass
        if t >= BOOT_SURE:
            self._finish()
            return
        self.update()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self.hide()
        if self._on_finish:
            try:
                self._on_finish()
            except Exception as e:
                print("Acilis sonrasi baslatma hatasi:", e)

    def paintEvent(self, _):
        try:
            self._paint()
        except Exception as e:
            print("Acilis cizim hatasi:", e)

    def _paint(self):
        if self._t0 is None:
            return
        t = time.monotonic() - self._t0
        T = BOOT_SURE
        fade_in = _ease(t / 0.6)
        fade_out = 1.0 - _ease((t - (T - 0.7)) / 0.7)
        f = max(0.0, min(1.0, fade_in * fade_out))
        prog = _ease((t - 0.5) / (T - 2.4))               # 0..1 ilerleme
        online = _ease((t - (T - 1.9)) / 0.5)              # son asama: CEVRIMICI
        flash = max(0.0, 1.0 - abs(t - (T - 1.9)) / 0.35)  # gecis parlamasi

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        def col(c, a):
            return QColor(c.red(), c.green(), c.blue(), max(0, min(255, int(a * f))))

        # ── panel ──
        panel = QRectF(10, 10, W - 20, H - 20)
        bg = QLinearGradient(0, 10, 0, H - 10)
        bg.setColorAt(0.0, QColor(3, 14, 26, int(225 * f)))
        bg.setColorAt(1.0, QColor(2, 8, 16, int(235 * f)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(panel, 16, 16)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col(CYAN, 80), 1.2))
        p.drawRoundedRect(panel, 16, 16)
        L = 36
        p.setPen(QPen(col(CYAN, 235), 2.8))
        for (cx_, cy_, dx, dy) in ((20, 20, 1, 1), (W - 20, 20, -1, 1), (20, H - 20, 1, -1), (W - 20, H - 20, -1, -1)):
            p.drawLine(QPointF(cx_, cy_), QPointF(cx_ + dx * L, cy_))
            p.drawLine(QPointF(cx_, cy_), QPointF(cx_, cy_ + dy * L))

        # ── ust yazi ──
        hf = QFont("Segoe UI", 11)
        hf.setBold(True)
        hf.setLetterSpacing(QFont.AbsoluteSpacing, 4.0)
        p.setFont(hf)
        p.setPen(col(CYAN_LIGHT, 230))
        p.drawText(QRectF(40, 28, 400, 24), Qt.AlignLeft | Qt.AlignVCenter, "STARK İNDÜSTRİ  //  J.A.R.V.I.S")
        mf = QFont("Consolas", 9)
        mf.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(mf)
        p.setPen(col(CYAN, 190))
        p.drawText(QRectF(W - 300, 28, 260, 24), Qt.AlignRight | Qt.AlignVCenter,
                   datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))

        # ── arc reactor ──
        cx, cy = W / 2.0, 236.0
        R = 118.0 * (0.55 + 0.45 * _ease(t / 1.0))
        pulse = 0.5 + 0.5 * math.sin(t * 5.0)
        glow = QRadialGradient(QPointF(cx, cy), R * 1.9)
        glow.setColorAt(0.0, col(CYAN, 70 + 70 * online + 120 * flash))
        glow.setColorAt(0.6, col(CYAN, 22))
        glow.setColorAt(1.0, col(CYAN, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), R * 1.9, R * 1.9)

        # genisleyen sinyal halkalari
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            u = ((t * 0.55) + i / 3.0) % 1.0
            p.setPen(QPen(col(CYAN, 120 * (1 - u)), 1.6))
            p.drawEllipse(QPointF(cx, cy), R * (1.0 + 0.9 * u), R * (1.0 + 0.9 * u))
        # dis halka + olcek
        p.setPen(QPen(col(CYAN, 200), 2.2))
        p.drawEllipse(QPointF(cx, cy), R, R)
        p.setPen(QPen(col(CYAN, 130), 1.4))
        for deg in range(0, 360, 6):
            rad = math.radians(deg + t * 20)
            r2 = R * (1.09 if deg % 30 == 0 else 1.05)
            p.drawLine(QPointF(cx + R * math.cos(rad), cy + R * math.sin(rad)),
                       QPointF(cx + r2 * math.cos(rad), cy + r2 * math.sin(rad)))
        # ilerleme yayi (turuncu): reactor cevresinde
        p.setPen(QPen(col(AMBER, 245), 4.0))
        rr = QRectF(cx - R * 1.2, cy - R * 1.2, R * 2.4, R * 2.4)
        p.drawArc(rr, 90 * 16, int(-prog * 360 * 16))
        # reactor segmentleri (ters donen kalin yaylar)
        p.setPen(QPen(col(CYAN, 235), 7.0, Qt.SolidLine, Qt.FlatCap))
        base = -t * 50.0
        for k in range(10):
            a0 = base + k * 36
            p.drawArc(QRectF(cx - R * 0.72, cy - R * 0.72, R * 1.44, R * 1.44), int(a0 * 16), int(24 * 16))
        p.setPen(QPen(col(CYAN_LIGHT, 200), 2.0))
        p.drawEllipse(QPointF(cx, cy), R * 0.52, R * 0.52)
        # cekirdek
        core = QRadialGradient(QPointF(cx, cy), R * 0.5)
        core.setColorAt(0.0, QColor(235, 252, 255, int(255 * f)))
        core.setColorAt(0.45, col(CYAN, 190 + 60 * pulse))
        core.setColorAt(1.0, col(CYAN, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(core))
        p.drawEllipse(QPointF(cx, cy), R * 0.5, R * 0.5)
        # ucgen cekirdek cercevesi
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col(CYAN_LIGHT, 230), 2.0))
        tri_r = R * 0.3
        pts = [QPointF(cx + tri_r * math.cos(math.radians(a + t * 40)), cy + tri_r * math.sin(math.radians(a + t * 40)))
               for a in (90, 210, 330)]
        for i in range(3):
            p.drawLine(pts[i], pts[(i + 1) % 3])

        # ── sol: sistem kontrol satirlari ──
        cf = QFont("Consolas", 10)
        p.setFont(cf)
        y = 118
        for name, th in CHECKS:
            if prog >= th - 0.02:
                ok = prog >= th + 0.10
                p.setPen(col(CYAN, 220))
                p.drawText(QRectF(40, y, 230, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
                p.setPen(col(AMBER if not ok else QColor(120, 255, 170), 240))
                p.drawText(QRectF(40, y, 232, 18), Qt.AlignRight | Qt.AlignVCenter,
                           "TAMAM" if ok else ("." * (1 + int(t * 6) % 3)))
            y += 26

        # ── sag: canli CPU / RAM ──
        p.setFont(cf)
        rx = W - 270
        p.setPen(col(CYAN, 200))
        p.drawText(QRectF(rx, 118, 230, 18), Qt.AlignLeft | Qt.AlignVCenter, "İŞLEMCİ")
        p.drawText(QRectF(rx, 118, 230, 18), Qt.AlignRight | Qt.AlignVCenter, "%d%%" % self._cpu)
        p.drawText(QRectF(rx, 144, 230, 18), Qt.AlignLeft | Qt.AlignVCenter, "BELLEK")
        p.drawText(QRectF(rx, 144, 230, 18), Qt.AlignRight | Qt.AlignVCenter, "%d%%" % self._ram)
        for i, v in enumerate((self._cpu, self._ram)):
            p.setPen(QPen(col(CYAN, 60), 1.0))
            p.drawRect(QRectF(rx, 136 + i * 26, 230, 5))
            p.setPen(Qt.NoPen)
            p.setBrush(col(CYAN, 200))
            p.drawRect(QRectF(rx, 136 + i * 26, 230 * min(100, v) / 100.0, 5))
        p.setBrush(Qt.NoBrush)
        p.setPen(col(CYAN, 160))
        for i, ln in enumerate(("DURUM  BAŞLATILIYOR", "PROTOKOL  V7", "KANAL  ŞİFRELİ")):
            p.drawText(QRectF(rx, 190 + i * 22, 230, 18), Qt.AlignLeft | Qt.AlignVCenter, ln)

        # ── alt: ilerleme cubugu / CEVRIMICI ──
        bx, bw = 60.0, W - 120.0
        by = 440.0
        if online < 0.02:
            p.setPen(QPen(col(CYAN, 90), 1.2))
            p.drawRect(QRectF(bx, by, bw, 10))
            p.setPen(Qt.NoPen)
            g = QLinearGradient(bx, 0, bx + bw, 0)
            g.setColorAt(0.0, col(CYAN, 220))
            g.setColorAt(1.0, col(AMBER, 240))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(bx, by, bw * prog, 10))
            p.setBrush(Qt.NoBrush)
            p.setPen(col(CYAN_LIGHT, 230))
            p.drawText(QRectF(bx, by + 14, bw, 18), Qt.AlignCenter, "%d%%" % int(prog * 100))
        else:
            ff = QFont("Segoe UI", 20)
            ff.setBold(True)
            ff.setLetterSpacing(QFont.AbsoluteSpacing, 6.0 + 8.0 * (1 - online))
            p.setFont(ff)
            p.setPen(col(CYAN_LIGHT, 255 * online))
            p.drawText(QRectF(0, by - 14, W, 44), Qt.AlignCenter, "J.A.R.V.I.S  ONLINE")
            p.setPen(QPen(col(AMBER, 230 * online), 2))
            half = 210 * online
            p.drawLine(QPointF(cx - half, by + 38), QPointF(cx + half, by + 38))
        # gecis parlamasi
        if flash > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(col(CYAN_LIGHT, 55 * flash))
            p.drawRoundedRect(panel, 16, 16)
        p.end()
