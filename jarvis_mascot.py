# -*- coding: utf-8 -*-
"""
JARVIS MASKOT YÜZÜ
==================
Beyaz yuvarlak gövde, siyah oval gözler, gövdeden ayrı duran iki el.
Eski JarvisFace ile AYNI arayüze sahip (set_status, set_label, clicked),
yani jarvis_voice.py'de yerine takılabilir.

NE YAPAR:
  - Açılışta ve JARVIS uyanınca sağ eliyle el sallar (wave)
  - Gözleri kırpar, ara sıra etrafa bakar, nefes alır gibi hafifçe kabarır
  - idle      -> sakin, gözler biraz kısık, soluk parıltı
  - listening -> gözler iri ve açık, mavi parıltı
  - speaking  -> gövde konuşurken hafifçe zıplar, altın parıltı, eller oynar
  - Tıklayınca küçük bir zıplama yapar ve clicked sinyalini yollar
"""

import math
import random
import time

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QRadialGradient, QLinearGradient,
                         QPainterPath, QFont, QFontMetrics)
from PyQt5.QtWidgets import QWidget

# ── Ayarlar (istersen buradan oynayabilirsin) ──
BODY_W, BODY_H, BODY_R = 112.0, 88.0, 36.0     # gövde (250x250'lik alana göre)
HAND_RADIUS = 13.0                              # sol el (daire)
HAND_LEN, HAND_WID = 38.0, 17.0                 # sağ el (hap şekli)
WAVE_DURATION = 2.6                             # el sallama süresi (sn)
WAVE_COOLDOWN = 6.0                             # iki el sallama arası en az süre (sn)

_PRESETS = {
    #            göz açıklığı, göz boyu, nefes, hız,  parıltı (r,g,b,a),      bakış yukarı
    "idle":      dict(eye_open=0.85, eye_scale=1.00, breathe=0.012, speed=1.3, glow=(255, 235, 200, 34), look_up=0.0),
    "listening": dict(eye_open=1.00, eye_scale=1.12, breathe=0.020, speed=2.2, glow=(0, 200, 255, 80),   look_up=-2.0),
    "speaking":  dict(eye_open=1.00, eye_scale=1.00, breathe=0.000, speed=1.0, glow=(255, 196, 90, 78),  look_up=0.0),
}


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _lerp(a, b, t):
    return a + (b - a) * t


class JarvisMascot(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0 = time.monotonic()
        self._last_t = 0.0
        self._status = "idle"
        self._label = ""

        # animasyonla yumuşakça değişen değerler
        p = _PRESETS["idle"]
        self._eye_open = p["eye_open"]
        self._eye_scale = p["eye_scale"]
        self._breathe = p["breathe"]
        self._speed = p["speed"]
        self._glow = list(map(float, p["glow"]))
        self._look_up = p["look_up"]
        self._talk_amt = 0.0

        self._wave_start = None
        self._last_wave = -999.0
        self._bounce_start = None
        self._follow = None                        # fareyi izle: QPointF (goz kaymasi) ya da None
        self._dance_start = None
        self._dance_dir = 0
        self._dance_dur = 1.4
        self._flash_start = None
        self._happy_until = 0.0

        self._blink_start = None
        self._next_blink = random.uniform(2.0, 4.0)
        self._look = QPointF(0, 0)
        self._look_target = QPointF(0, 0)
        self._next_look = random.uniform(2.5, 5.0)
        self._shown_once = False

        self._look_gain = 1.0                      # bakis hareketi carpani (ada icin buyutulur)
        self._bounce_gain = 1.0                    # ziplama yuksekligi carpani
        self._look_interval = (2.5, 6.0)           # kac saniyede bir etrafa baksin
        self._draw_card = True                     # False: koyu kart cizilmez (ada icin)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)                      # ~30 kare/sn

    # ── dışarıdan kullanılan arayüz (JarvisFace ile aynı) ──
    def set_status(self, s):
        s = str(s).lower()
        if s in ("speaking", "speak", "talking"):
            self._status = "speaking"
        elif s in ("idle", "standby", "sleep"):
            self._status = "idle"
        else:
            self._status = "listening"

    def set_label(self, text):
        self._label = str(text)

    def set_follow(self, x, y):
        """Gozler (x, y) yonune bakar (fare takibi). x None ise serbest bakis."""
        self._follow = None if x is None else QPointF(float(x), float(y))

    def dance(self, direction=0, dur=1.4):
        """Dans: yana sallanir, zipalar, eller havada. direction: +1 saga, -1 sola egilir."""
        now = self._now()
        self._dance_start = now
        self._dance_dir = direction
        self._dance_dur = dur
        self._wave_start = None
        self._last_wave = now              # el sallama araya girmesin

    def flash(self):
        """Fotograf flasi gibi beyaz parlama + kisa sure mutlu goz."""
        now = self._now()
        self._flash_start = now
        self._happy_until = now + 0.8

    def cheer(self, dur=0.9):
        """Kisa sevinc: mutlu goz + zipla."""
        now = self._now()
        self._happy_until = now + dur
        self._bounce_start = now

    def wave(self):
        """El salla. Çok sık çağrılırsa (6 sn içinde) yok sayılır."""
        if self._dance_start is not None:
            return
        now = self._now()
        if now - self._last_wave < WAVE_COOLDOWN:
            return
        self._last_wave = now
        self._wave_start = now

    # ── yardımcılar ──
    def _now(self):
        return time.monotonic() - self._t0

    def showEvent(self, e):
        super().showEvent(e)
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(500, self.wave)      # açılışta merhaba de

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._bounce_start = self._now()
            self.clicked.emit()

    # ── durum güncelleme (her karede) ──
    def _step(self, t, dt):
        preset = _PRESETS[self._status]
        a = 1.0 - math.exp(-dt * 7.0)              # yumuşak geçiş katsayısı
        self._eye_open = _lerp(self._eye_open, preset["eye_open"], a)
        self._eye_scale = _lerp(self._eye_scale, preset["eye_scale"], a)
        self._breathe = _lerp(self._breathe, preset["breathe"], a)
        self._speed = _lerp(self._speed, preset["speed"], a)
        self._look_up = _lerp(self._look_up, preset["look_up"], a)
        for i in range(4):
            self._glow[i] = _lerp(self._glow[i], preset["glow"][i], a)
        self._talk_amt = _lerp(self._talk_amt, 1.0 if self._status == "speaking" else 0.0, a)

        # göz kırpma
        if self._blink_start is None and t >= self._next_blink:
            self._blink_start = t
        if self._blink_start is not None and t - self._blink_start > 0.16:
            self._blink_start = None
            self._next_blink = t + random.uniform(2.5, 5.5)

        # etrafa bakma (fare takibi aciksa fareye bakar)
        if self._follow is not None:
            self._look_target = self._follow
            self._next_look = t + 1.0
            k = min(1.0, a * 1.4)
        else:
            if t >= self._next_look:
                if random.random() < 0.6:
                    self._look_target = QPointF(random.uniform(-4, 4), random.uniform(-2, 2))
                else:
                    self._look_target = QPointF(0, 0)
                self._next_look = t + random.uniform(*self._look_interval)
            k = a * 0.6
        self._look = QPointF(_lerp(self._look.x(), self._look_target.x(), k),
                             _lerp(self._look.y(), self._look_target.y(), k))

    # ── çizim ──
    def paintEvent(self, _):
        t = self._now()
        dt = max(0.0, min(0.1, t - self._last_t)) if self._last_t else 0.033
        self._last_t = t
        self._step(t, dt)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        W, H = float(self.width()), float(self.height())
        s = min(W, H) / 250.0
        cx, cy = W / 2.0, H / 2.0 - 12 * s

        # koyu kart
        if self._draw_card:
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))
            p.setBrush(QColor(12, 14, 20, 240))
            p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 20 * s, 20 * s)

        # ── el sallama zaman çizelgesi ──
        wave_amt, swing, happy, tilt = 0.0, 0.0, False, 0.0
        if self._wave_start is not None:
            wt = t - self._wave_start
            if wt >= WAVE_DURATION:
                self._wave_start = None
            else:
                wave_amt = min(_smooth(wt / 0.35), _smooth((WAVE_DURATION - wt) / 0.4))
                swing = math.sin((wt - 0.2) * 11.0) * 22.0 * wave_amt
                happy = 0.25 < wt < WAVE_DURATION - 0.25
                tilt = 3.0 * math.sin(wt * 5.5) * wave_amt

        # zıplama (tıklayınca)
        bounce = 0.0
        if self._bounce_start is not None:
            bt = t - self._bounce_start
            if bt > 0.6:
                self._bounce_start = None
            else:
                bounce = -10 * s * self._bounce_gain * abs(math.sin(bt * math.pi / 0.3)) * (1 - bt / 0.6)

        # dans
        if self._dance_start is not None:
            dt_ = t - self._dance_start
            if dt_ >= self._dance_dur:
                self._dance_start = None
            else:
                amt = min(_smooth(dt_ / 0.2), _smooth((self._dance_dur - dt_) / 0.3))
                ph = dt_ * 8.5
                bounce += -abs(math.sin(ph)) * 9 * s * amt
                tilt += 8.0 * math.sin(ph) * amt
                cx += (math.sin(ph) * 7 + self._dance_dir * 6) * s * amt
                wave_amt = max(wave_amt, amt)
                swing = math.sin(dt_ * 13.0) * 26.0 * amt
                happy = True
        if t < self._happy_until:
            happy = True

        # konuşma hareketi
        talk = (0.5 + 0.5 * math.sin(t * 9.0)) * (0.55 + 0.45 * math.sin(t * 3.1))
        sy = 1.0 + self._breathe * math.sin(t * self._speed * 2.0) + 0.05 * self._talk_amt * talk
        sx = 1.0 - (sy - 1.0) * 0.6

        # ── parıltı ──
        gr, gg, gb, ga = self._glow
        if self._status == "listening":
            ga *= 0.8 + 0.2 * math.sin(t * 3.0)
        glow = QRadialGradient(QPointF(cx, cy + bounce), 135 * s)
        glow.setColorAt(0.0, QColor(int(gr), int(gg), int(gb), int(max(0, ga))))
        glow.setColorAt(1.0, QColor(int(gr), int(gg), int(gb), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy + bounce), 135 * s, 135 * s)

        # ── gövde ──
        p.save()
        p.translate(cx, cy + bounce)
        p.rotate(tilt)
        p.scale(sx, sy)
        body_rect = QRectF(-BODY_W / 2 * s, -BODY_H / 2 * s, BODY_W * s, BODY_H * s)
        grad = QLinearGradient(0, body_rect.top(), 0, body_rect.bottom())
        grad.setColorAt(0.0, QColor(255, 255, 255))
        grad.setColorAt(1.0, QColor(228, 231, 238))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(body_rect, BODY_R * s, BODY_R * s)
        self._draw_eyes(p, s, t, happy)
        p.restore()

        # ── eller ──
        bob = 2.5 * s * math.sin(t * 2.1)
        hand_fill = QColor(246, 247, 250)
        p.setPen(Qt.NoPen)
        p.setBrush(hand_fill)

        # sol el (daire)
        lx = cx - 74 * s
        ly = cy + 24 * s + bounce + bob * 1.0 + 3 * s * wave_amt * math.sin(t * 8.0)
        p.drawEllipse(QPointF(lx, ly), HAND_RADIUS * s, HAND_RADIUS * s)

        # sağ el (hap): omuz noktasından açıyla uzanır
        pivot = QPointF(cx + _lerp(50, 52, wave_amt) * s, cy + _lerp(6, 10, wave_amt) * s + bounce)
        angle = _lerp(-28.0, -72.0, wave_amt) + swing
        if self._talk_amt > 0.01:
            angle += 6.0 * self._talk_amt * math.sin(t * 6.0)       # konuşurken jest yapar
        dist = _lerp(33.0, 46.0, wave_amt) * s
        rad = math.radians(angle)
        hx = pivot.x() + dist * math.cos(rad)
        hy = pivot.y() + dist * math.sin(rad) + (bob if wave_amt < 0.05 else 0.0)
        p.save()
        p.translate(hx, hy)
        p.rotate(angle)
        p.drawRoundedRect(QRectF(-HAND_LEN / 2 * s, -HAND_WID / 2 * s, HAND_LEN * s, HAND_WID * s),
                          HAND_WID / 2 * s, HAND_WID / 2 * s)
        p.restore()

        # ── flas ──
        if self._flash_start is not None:
            ft = t - self._flash_start
            if ft > 0.45:
                self._flash_start = None
            else:
                fa = int(235 * (1.0 - ft / 0.45) ** 1.6)
                fg = QRadialGradient(QPointF(cx, cy + bounce), 125 * s)
                fg.setColorAt(0.0, QColor(255, 255, 255, fa))
                fg.setColorAt(0.6, QColor(255, 255, 255, int(fa * 0.45)))
                fg.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(fg))
                p.drawEllipse(QPointF(cx, cy + bounce), 125 * s, 125 * s)

        # ── alt yazı ──
        if self._label:
            f = QFont("Segoe UI", 8)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
            f.setFamilies(["Segoe UI", "Arial", "DejaVu Sans"])
            p.setFont(f)
            p.setPen(QColor(150, 160, 182))
            text = QFontMetrics(f).elidedText(self._label, Qt.ElideRight, int(W - 30))
            p.drawText(QRectF(0, H - 30 * s, W, 20 * s), Qt.AlignCenter, text)
        p.end()

    def _draw_eyes(self, p, s, t, happy):
        ink = QColor(14, 14, 18)
        # göz kırpma çarpanı
        blink = 1.0
        if self._blink_start is not None:
            u = (t - self._blink_start) / 0.16
            blink = max(0.08, 1.0 - math.sin(math.pi * min(1.0, max(0.0, u))))
        ex = 15.0 * s
        ey = -2.0 * s + (self._look.y() * self._look_gain + self._look_up) * s
        ox = self._look.x() * s * self._look_gain
        if happy:
            # mutlu göz: ^ ^
            p.setBrush(Qt.NoBrush)
            pen = QPen(ink, 3.2 * s)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            for sign in (-1, 1):
                path = QPainterPath()
                r = QRectF(sign * ex + ox - 6.5 * s, ey - 3 * s, 13 * s, 12 * s)
                path.arcMoveTo(r, 20)
                path.arcTo(r, 20, 140)
                p.drawPath(path)
        else:
            rx = 3.8 * s * self._eye_scale
            ry = 6.8 * s * self._eye_scale * self._eye_open * blink
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            for sign in (-1, 1):
                p.drawEllipse(QPointF(sign * ex + ox, ey), rx, ry)