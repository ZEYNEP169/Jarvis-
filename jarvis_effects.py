# -*- coding: utf-8 -*-
"""

Icerik:
  1) BootSplash        -> acilis animasyonu (sistem baslatiliyor ekrani)
  2) WaveWidget         -> gercek mikrofon seviyesine tepki veren ses dalgasi
  3) RadialMenu         -> Iron Man tarzi dairesel hologram komut menusu
  4) beep(kind)         -> kisa elektronik bip sesleri
  5) effect_signals     -> ses seviyesini disaridan (jarvis_voice.py) beslemek icin sinyal
"""

import os
import sys
import math
import time
import random
import threading

from PyQt5.QtWidgets import QWidget, QPushButton, QApplication
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QRadialGradient

CYAN   = QColor(0, 210, 255)
GOLD   = QColor(255, 190, 0)
DIM    = QColor(0, 120, 170)
BG     = QColor(0, 0, 0)


def qfont(size, bold=False):
    f = QFont("Consolas", size)
    f.setBold(bold)
    f.setStyleHint(QFont.Monospace)
    f.setFamilies(["Consolas", "Courier New", "DejaVu Sans Mono", "Monospace"])
    return f


# ══════════════════════════════════════════════════════════
#  ORTAK SINYAL (mikrofon seviyesini widget'lara ulastirmak icin)
# ══════════════════════════════════════════════════════════
class EffectSignals(QObject):
    voice_level = pyqtSignal(float)   # 0.0 - 1.0 arasi anlik ses seviyesi


effect_signals = EffectSignals()


# ══════════════════════════════════════════════════════════
#  1) BOOT SPLASH - Acilis animasyonu
# ══════════════════════════════════════════════════════════
class BootSplash(QWidget):
    """
    Ekranda 2.5 saniye kadar goruntulenen, Iron Man / JARVIS tarzi
    'sistem baslatiliyor' animasyonu. Bitince on_finish() cagirir.
    """
    LINES = [
        "INITIALIZING J.A.R.V.I.S CORE...",
        "LOADING VOICE RECOGNITION MODULE...",
        "CALIBRATING AUDIO SENSORS...",
        "CONNECTING NEURAL NETWORK...",
        "ALL SYSTEMS OPERATIONAL",
    ]

    def __init__(self, on_finish=None):
        super().__init__()
        self.on_finish = on_finish
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(520, 420)
        scr = QApplication.primaryScreen().geometry()
        self.move((scr.width() - self.width()) // 2, (scr.height() - self.height()) // 2)

        self.angle = 0.0
        self.line_index = 0
        self.visible_lines = []
        self.progress = 0.0   # 0..1 dis halkanin dolma orani

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(30)

        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self._next_line)
        self.text_timer.start(480)

        # toplam ~2.6 saniye sonra kapan
        QTimer.singleShot(2600, self._finish)

    def _tick(self):
        self.angle = (self.angle + 4) % 360
        self.progress = min(1.0, self.progress + 0.012)
        self.update()

    def _next_line(self):
        if self.line_index < len(self.LINES):
            self.visible_lines.append(self.LINES[self.line_index])
            self.line_index += 1
            self.update()
        else:
            self.text_timer.stop()

    def _finish(self):
        self.anim_timer.stop()
        self.text_timer.stop()
        self.close()
        if self.on_finish:
            self.on_finish()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h * 0.38
        R = 90

        # arka plan hafif parlama
        glow = QRadialGradient(cx, cy, R * 2.2)
        glow.setColorAt(0.0, QColor(0, 120, 255, 60))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), R * 2.2, R * 2.2)

        # dis dolan halka (yukleme yuzdesi)
        p.setPen(QPen(QColor(0, 80, 110, 120), 6))
        p.drawEllipse(QPointF(cx, cy), R, R)
        p.setPen(QPen(CYAN, 6))
        p.drawArc(QRectF(cx - R, cy - R, R * 2, R * 2), 90 * 16, -int(360 * 16 * self.progress))

        # donen ic halka
        p.save()
        p.translate(cx, cy)
        p.rotate(self.angle)
        p.setPen(QPen(GOLD, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), R * 0.65, R * 0.22)
        p.restore()

        # merkez yazi
        p.setPen(CYAN)
        p.setFont(qfont(20, True))
        p.drawText(QRectF(cx - R, cy - 12, R * 2, 24), Qt.AlignCenter, "J.A.R.V.I.S")

        # yuzde
        p.setPen(GOLD)
        p.setFont(qfont(11, True))
        p.drawText(QRectF(cx - R, cy + 16, R * 2, 20), Qt.AlignCenter,
                   f"{int(self.progress * 100)}%")

        # alt log satirlari
        p.setFont(qfont(10))
        y = cy + R + 50
        for i, line in enumerate(self.visible_lines):
            alpha = 255 if i == len(self.visible_lines) - 1 else 140
            col = QColor(CYAN)
            col.setAlpha(alpha)
            p.setPen(col)
            p.drawText(QRectF(20, y, w - 40, 20), Qt.AlignLeft, "> " + line)
            y += 22


# ══════════════════════════════════════════════════════════
#  2) GERCEK SES DALGASI (mikrofon seviyesine gore)
# ══════════════════════════════════════════════════════════
class WaveWidget(QWidget):
    """
    effect_signals.voice_level sinyaline abone olur; jarvis_voice.py
    tarafindan mikrofon seviyesi geldikce cubuklar gercekten oynar.
    """
    BAR_COUNT = 24

    def __init__(self):
        super().__init__()
        self.setFixedHeight(42)
        self.levels = [0.03] * self.BAR_COUNT
        self.target = 0.03
        effect_signals.voice_level.connect(self.set_level)

        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(45)

    def set_level(self, v):
        self.target = max(0.03, min(1.0, v))

    def _tick(self):
        # yeni deger sona eklenir, cubuklar sola kayar (gercek dalga hissi)
        self.levels.pop(0)
        jitter = random.uniform(0.85, 1.0)
        self.levels.append(self.target * jitter)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))
        bw = w / self.BAR_COUNT
        for i, lvl in enumerate(self.levels):
            bh = max(2, lvl * (h - 4))
            x = i * bw + bw * 0.15
            y = (h - bh) / 2
            col = QColor(CYAN)
            col.setAlphaF(0.45 + 0.55 * lvl)
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(int(x), int(y), max(1, int(bw * 0.7)), int(bh), 2, 2)


# ══════════════════════════════════════════════════════════
#  3) DAIRESEL HOLOGRAM KOMUT MENUSU
# ══════════════════════════════════════════════════════════
class RadialMenu(QWidget):
    """
    Ekranin ortasinda yari saydam, dairesel dizilmis komut butonlari.
    Bir butona tiklaninca 'on_select(command_text)' cagirir ve kapanir.
    """
    def __init__(self, items, on_select, parent=None):
        """
        items: [(gorunen_ad, komut_metni), ...]
        on_select: fn(komut_metni)
        """
        super().__init__(parent)
        self.on_select = on_select
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        scr = QApplication.primaryScreen().geometry()
        self.resize(scr.width(), scr.height())
        self.move(0, 0)

        self.cx, self.cy = scr.width() / 2, scr.height() / 2
        self.radius = 170
        self.buttons = []
        self.angle_offset = 0.0

        n = len(items)
        for i, (name, cmd) in enumerate(items):
            ang = (2 * math.pi * i / n) - math.pi / 2
            btn = QPushButton(name, self)
            btn.setFixedSize(96, 40)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(0,25,45,220); color: rgb(0,210,255);
                    border: 1px solid rgba(0,210,255,150); border-radius: 6px;
                    font-family: 'Consolas'; font-size: 10px; font-weight: bold;
                }
                QPushButton:hover { background: rgba(0,70,110,230); border-color: rgb(255,190,0); }
            """)
            btn.clicked.connect(lambda _, c=cmd: self._choose(c))
            x = self.cx + math.cos(ang) * self.radius - btn.width() / 2
            y = self.cy + math.sin(ang) * self.radius - btn.height() / 2
            btn.move(int(x), int(y))
            self.buttons.append(btn)

        close_btn = QPushButton("✕", self)
        close_btn.setFixedSize(46, 46)
        close_btn.setStyleSheet("""
            QPushButton { background: rgba(255,50,50,180); color: white; border: none;
                border-radius: 23px; font-weight: bold; font-size: 16px; }
            QPushButton:hover { background: rgba(255,90,90,220); }
        """)
        close_btn.move(int(self.cx - 23), int(self.cy - 23))
        close_btn.clicked.connect(self.close)
        self.close_btn = close_btn

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

        for b in self.buttons:
            b.show()
        close_btn.show()

    def _tick(self):
        self.angle_offset = (self.angle_offset + 0.6) % 360
        self.update()

    def _choose(self, cmd):
        self.close()
        if self.on_select:
            self.on_select(cmd)

    def mousePressEvent(self, e):
        # butonlarin disina tiklayinca kapat
        pos = e.pos()
        if (pos.x() - self.cx) ** 2 + (pos.y() - self.cy) ** 2 > (self.radius + 70) ** 2:
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))

        # dis donen halka
        p.save()
        p.translate(self.cx, self.cy)
        p.rotate(self.angle_offset)
        p.setPen(QPen(QColor(0, 210, 255, 90), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), self.radius + 55, self.radius + 55)
        p.restore()

        p.setPen(QPen(QColor(0, 210, 255, 140), 1.5))
        p.drawEllipse(QPointF(self.cx, self.cy), self.radius, self.radius)

        # merkezden butonlara ince cizgiler
        p.setPen(QPen(QColor(0, 210, 255, 60), 1))
        for b in self.buttons:
            bc = b.geometry().center()
            p.drawLine(QPointF(self.cx, self.cy), QPointF(bc))


# ══════════════════════════════════════════════════════════
#  4) BIP SESLERI
# ══════════════════════════════════════════════════════════
def _beep_windows(freq, dur_ms):
    try:
        import winsound
        winsound.Beep(int(freq), int(dur_ms))
    except Exception:
        pass


def beep(kind="ok"):
    """
    kind: 'wake' (uyanma), 'chime' (konusma oncesi kisa bip),
          'ok' (onay), 'error' (hata/anlasilmadi)
    Sadece Windows'ta ses cikarir (winsound), diger sistemlerde sessiz gecer.
    """
    if os.name != "nt":
        return

    def _run():
        if kind == "wake":
            _beep_windows(600, 90); _beep_windows(900, 110)
        elif kind == "chime":
            _beep_windows(1200, 60)
        elif kind == "ok":
            _beep_windows(1000, 70); _beep_windows(1400, 70)
        elif kind == "error":
            _beep_windows(300, 180)
        else:
            _beep_windows(800, 80)

    threading.Thread(target=_run, daemon=True).start()
# ══════════════════════════════════════════════════════════
#  5) MATERIALIZE / DEMATERIALIZE GECIS EFEKTI
# ══════════════════════════════════════════════════════════
class MaterializeOverlay(QWidget):
    """
    JARVIS yuzunun ustune binen, saydam bir katman.
    start('in')  -> parcaciklar disaridan merkeze toplanir (JARVIS 'belirir')
    start('out') -> parcaciklar merkezden disariya dagilir (JARVIS 'kaybolur')
    """
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.particles = []
        self.mode = None
        self.progress = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self, mode):
        self.mode = mode
        self.progress = 0.0
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(cx, cy)
        self.particles = []
        for _ in range(70):
            ang = random.uniform(0, 2 * math.pi)
            dist = random.uniform(0.35, 1.0) * R
            self.particles.append((ang, dist))
        self.show()
        self.raise_()
        self._timer.start(16)

    def _tick(self):
        self.progress += 0.05
        if self.progress >= 1.0:
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        t = self.progress
        k = (1 - t) if self.mode == "in" else t
        alpha = t if self.mode == "in" else (1 - t)
        for ang, dist in self.particles:
            cur = dist * k
            x = cx + math.cos(ang) * cur
            y = cy + math.sin(ang) * cur
            col = QColor(0, 210, 255, max(0, min(255, int(255 * alpha))))
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.end()