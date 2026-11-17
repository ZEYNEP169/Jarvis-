import math
import random

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont, QRadialGradient


class Signals(QObject):
    set_status   = pyqtSignal(str)
    set_text     = pyqtSignal(str)
    show_ui      = pyqtSignal()
    hide_ui      = pyqtSignal()
    set_heard    = pyqtSignal(str)
    process_text = pyqtSignal(str)

signals = Signals()


class JarvisFace(QWidget):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.angle  = 0
        self.angle2 = 0
        self.angle3 = 0
        self.pulse  = 0.0
        self.bars   = [4]*8
        self.status = "idle"
        self.label  = "STANDBY"
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(16)

    def _tick(self):
        self.angle  = (self.angle  + 0.5) % 360
        self.angle2 = (self.angle2 - 0.3) % 360
        self.angle3 = (self.angle3 + 1.0) % 360
        self.pulse  = (self.pulse  + 0.02) % 1.0
        if self.status == "speaking":
            self.bars = [random.randint(6, 22) for _ in range(8)]
        elif self.status == "listening":
            self.bars = [random.randint(3, 8) for _ in range(8)]
        elif self.status == "thinking":
            self.bars = [random.randint(2, 6) for _ in range(8)]
        else:
            self.bars = [max(3, b - 1) for b in self.bars]
        self.update()

    def set_status(self, s): self.status = s
    def set_label(self, t):  self.label  = t

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        cx, cy = w/2, h/2
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(0, 0, 0))

        pen = QPen(QColor(0, 180, 255, 10))
        pen.setWidth(1)
        p.setPen(pen)
        for x in range(0, w, 30): p.drawLine(x, 0, x, h)
        for y in range(0, h, 30): p.drawLine(0, y, w, y)

        r1 = min(cx, cy) * 0.82
        r2 = r1 * 0.85
        r3 = r1 * 0.70
        r4 = r1 * 0.56

        def draw_ring(radius, color, width, rotation=0, dot=False):
            p.save()
            p.translate(cx, cy)
            p.rotate(rotation)
            p.setPen(QPen(color, width))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), radius, radius)
            if dot:
                p.setBrush(QBrush(color))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(0, -radius), 4, 4)
            p.restore()

        draw_ring(r1, QColor(0, 180, 255, 160), 2, self.angle,  dot=True)
        draw_ring(r2, QColor(0, 180, 255,  80), 1, self.angle2, dot=True)
        draw_ring(r3, QColor(255, 200, 0,  130), 3, self.angle3)
        draw_ring(r4, QColor(0, 180, 255,  50),  1, -self.angle2)

        p.save()
        p.translate(cx, cy)
        p.rotate(self.angle)
        for i in range(60):
            a = math.radians(i * 6)
            lng = i % 5 == 0
            p.setPen(QPen(QColor(0, 180, 255, 200 if lng else 100), 1.5))
            l = 10 if lng else 5
            p.drawLine(
                QPointF(math.sin(a) * (r1 - l), -math.cos(a) * (r1 - l)),
                QPointF(math.sin(a) * r1,        -math.cos(a) * r1))
        p.restore()

        pr = r4 * 0.55 * (1 + self.pulse * 1.2)
        draw_ring(pr, QColor(0, 180, 255, int(150 * (1 - self.pulse))), 1)

        grad = QRadialGradient(cx, cy, r4 * 0.55)
        grad.setColorAt(0.0, QColor(0, 40, 80, 180))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r4 * 0.55, r4 * 0.55)
        p.setPen(QPen(QColor(0, 180, 255, 80), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r4 * 0.55, r4 * 0.55)

        p.setFont(QFont("Courier New", max(6, int(r1 * 0.10)), QFont.Bold))
        p.setPen(QColor(0, 180, 255, 220))
        p.drawText(0, int(cy - 10), w, 20, Qt.AlignCenter, "J.A.R.V.I.S")
        p.setFont(QFont("Courier New", max(4, int(r1 * 0.06))))
        p.setPen(QColor(0, 180, 255, 120))
        p.drawText(0, int(cy + 6), w, 16, Qt.AlignCenter, "ONLINE")

        if self.status == "speaking":
            col = QColor(0, 220, 255)
        elif self.status == "thinking":
            col = QColor(255, 200, 0)
        else:
            col = QColor(0, 180, 255, 160)

        p.setFont(QFont("Courier New", max(5, int(r1 * 0.07))))
        p.setPen(col)
        p.drawText(0, int(cy + r1 * 0.75), w, 16, Qt.AlignCenter, self.label)

        bar_w = 3
        gap = 2
        total = 8 * bar_w + 7 * gap
        bx = cx - total / 2
        by = cy + r1 * 0.90
        for i, bh in enumerate(self.bars):
            x = bx + i * (bar_w + gap)
            if self.status == "speaking":
                color = QColor(0, 220, 255, 200)
            elif self.status == "thinking":
                color = QColor(255, 200, 0, 150)
            else:
                color = QColor(0, 180, 255, 60)
            p.fillRect(int(x), int(by - bh), bar_w, int(bh), color)

        p.end()
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)