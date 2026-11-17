import os
# --- YAZI GORUNMEME SORUNU ICIN: PyQt5 import edilmeden ONCE ayarlanmali ---
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


import sys
import math
import random
import datetime
import threading
import time
import json
import requests
import psutil

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                              QScrollArea, QFrame, QGridLayout, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QPointF, pyqtSignal, QObject, QThread
from PyQt5.QtGui import (QPainter, QPen, QColor, QBrush, QFont, QRadialGradient,
                          QLinearGradient, QPainterPath)

# ── Renkler ──
C_BG      = QColor(0, 0, 0)
C_PANEL   = QColor(5, 10, 20, 220)
C_BLUE    = QColor(0, 180, 255)
C_BLUE2   = QColor(0, 100, 180)
C_GOLD    = QColor(255, 200, 0)
C_GREEN   = QColor(0, 255, 136)
C_TEXT    = QColor(180, 230, 255)
C_DIM     = QColor(80, 140, 180)
C_BORDER  = QColor(0, 180, 255, 60)

# ── Ortak veri dosyalari (jarvis_voice.py ile de paylasilabilir) ──
DATA_DIR     = r"C:\Jarvis" if os.name == "nt" else os.path.expanduser("~/.jarvis")
EVENTS_FILE  = os.path.join(DATA_DIR, "events.json")
MEMORY_FILE  = os.path.join(DATA_DIR, "memory_log.json")
os.makedirs(DATA_DIR, exist_ok=True)
NET_FULL_SCALE_MBPS = 10   # NETWORK cubugu 10 MB/s'de dolar (YAMA_UYGULANDI_v1)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def append_memory(entry):
    """Son islenen komutlari/olaylari kalici olarak kaydeder (en fazla 50 tanesi tutulur)."""
    items = load_json(MEMORY_FILE, [])
    items.append({"time": datetime.datetime.now().strftime("%H:%M"), "text": entry})
    items = items[-50:]
    save_json(MEMORY_FILE, items)
    return items


def label(text, size=10, color=C_TEXT, bold=False):
    l = QLabel(text)
    f = QFont("Courier New", size)
    f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color: rgb({color.red()},{color.green()},{color.blue()}); background: transparent;")
    return l

def panel_style():
    return "background: rgba(5,10,20,220); border: 1px solid rgba(0,180,255,60); border-radius: 4px;"

# ══════════════════════════════════════════
#  Intel Orb — animasyonlu küre
# ══════════════════════════════════════════
class IntelOrb(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 260)
        self.angle = 0
        self.angle2 = 0
        self.pulse = 0.0
        self.particles = [(random.uniform(0, 2*math.pi),
                           random.uniform(0.3, 0.95),
                           random.uniform(0, 2*math.pi)) for _ in range(80)]
        self.speaking = False
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(16)

    def _tick(self):
        self.angle  = (self.angle  + 0.8) % 360
        self.angle2 = (self.angle2 - 0.5) % 360
        self.pulse  = (self.pulse  + 0.03) % (2 * math.pi)
        self.update()

    def set_speaking(self, v): self.speaking = v

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        cx, cy = w/2, h/2
        R = min(w, h) * 0.38
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, C_BG)

        # Dış parıltı
        glow = QRadialGradient(cx, cy, R*1.4)
        glow.setColorAt(0.0, QColor(0, 100, 255, 40))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), R*1.4, R*1.4)

        # Parçacıklar (küre yüzeyi)
        for phi, r, theta in self.particles:
            phi2 = phi + math.radians(self.angle * 0.5)
            x = cx + R * r * math.sin(phi2) * math.cos(theta)
            y = cy + R * r * math.cos(phi2)
            z = R * r * math.sin(phi2) * math.sin(theta)
            depth = (z / R + 1) / 2
            alpha = int(80 + 160 * depth)
            size  = 1.5 + 2.5 * depth
            color = QColor(0, int(120 + 100*depth), 255, alpha)
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), size, size)

        # Küre dış çemberi
        pen = QPen(QColor(0, 180, 255, 120), 1.5)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R, R)

        # Dönen halkalar
        for ang, col, w2 in [(self.angle, QColor(0,180,255,100), 1.5),
                              (self.angle2, QColor(255,200,0,80), 1)]:
            p.save()
            p.translate(cx, cy)
            p.rotate(ang)
            p.setPen(QPen(col, w2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), R*1.15, R*0.3)
            p.restore()

        # Nabız halkası
        pulse_r = R * (1.05 + 0.1 * math.sin(self.pulse))
        p.setPen(QPen(QColor(0, 180, 255, int(60 + 40*math.sin(self.pulse))), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), pulse_r, pulse_r)

        p.end()

# ══════════════════════════════════════════
#  Ses dalgası widget
# ══════════════════════════════════════════
class WaveWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(50)
        self.bars = [2]*30
        self.active = False
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(80)

    def _tick(self):
        if self.active:
            self.bars = [random.randint(4, 40) for _ in range(30)]
        else:
            self.bars = [max(2, b-3) for b in self.bars]
        self.update()

    def set_active(self, v): self.active = v

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(0,0,0,0))
        bw = w / len(self.bars)
        for i, bh in enumerate(self.bars):
            x = i * bw + bw*0.1
            y = (h - bh) / 2
            grad = QLinearGradient(x, y, x, y+bh)
            grad.setColorAt(0, QColor(0, 220, 255, 200))
            grad.setColorAt(1, QColor(0, 80, 180, 100))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(int(x), int(y), max(1, int(bw*0.8)), int(bh), 2, 2)
        p.end()

# ══════════════════════════════════════════
#  Bar göstergesi
# ══════════════════════════════════════════
class BarWidget(QWidget):
    def __init__(self, color=C_BLUE):
        super().__init__()
        self.setFixedHeight(6)
        self.value = 0
        self.color = color

    def set_value(self, v): self.value = max(0, min(100, v)); self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.fillRect(0, 0, w, h, QColor(20, 40, 60))
        fw = int(w * self.value / 100)
        grad = QLinearGradient(0, 0, fw, 0)
        grad.setColorAt(0, self.color.darker(150))
        grad.setColorAt(1, self.color)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRect(0, 0, fw, h)
        p.end()

# ══════════════════════════════════════════
#  Neural network görsel
# ══════════════════════════════════════════
class NeuralWidget(QWidget):
    """
    Dugum parlakligi CPU kullanimina, titresim hizi ise son 30 saniyedeki
    komut/islem yogunluguna (aktiviteye) baglidir. Boylece gorsel artik
    gercekten "ne kadar mesgul" oldugunu yansitir.
    """
    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        self.nodes = [(random.uniform(0.05, 0.95), random.uniform(0.1, 0.9)) for _ in range(12)]
        self.edges = [(random.randint(0,11), random.randint(0,11)) for _ in range(16)]
        self.pulse = 0.0
        self.cpu = 0.0
        self.activity = 0.0   # 0..1 arasi, son islemlere gore
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(50)

    def set_metrics(self, cpu, activity):
        self.cpu = cpu
        self.activity = activity

    def _tick(self):
        # aktivite yuksekse daha hizli titre
        speed = 0.03 + 0.12 * self.activity
        self.pulse = (self.pulse + speed) % (2*math.pi)
        self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(0,0,0,0))
        # CPU yuksekse baglantilar daha belirgin
        edge_alpha = int(25 + 1.2 * self.cpu)
        for i, j in self.edges:
            x1,y1 = self.nodes[i][0]*w, self.nodes[i][1]*h
            x2,y2 = self.nodes[j][0]*w, self.nodes[j][1]*h
            p.setPen(QPen(QColor(0,180,255,min(255,edge_alpha)), 1))
            p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
        base = int(70 + 1.6 * self.cpu)   # CPU'ya bagli taban parlaklik
        for i,(nx,ny) in enumerate(self.nodes):
            alpha = int(min(255, base + 80*math.sin(self.pulse + i)))
            p.setBrush(QBrush(QColor(0,180,255,max(30,alpha))))
            p.setPen(Qt.NoPen)
            size = 3 + 1.5 * self.activity
            p.drawEllipse(QPointF(nx*w, ny*h), size, size)
        p.end()

# ══════════════════════════════════════════
#  Sol panel
# ══════════════════════════════════════════
class LeftPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # System Overview
        sys_frame = QFrame()
        sys_frame.setStyleSheet(panel_style())
        sys_layout = QVBoxLayout(sys_frame)
        sys_layout.setContentsMargins(8,8,8,8)
        sys_layout.setSpacing(4)
        sys_layout.addWidget(label("SYSTEM OVERVIEW", 8, C_BLUE, True))

        self.bars = {}
        self.bar_labels = {}
        for name, icon in [("CPU","⚙"), ("RAM","◈"), ("STORAGE","▣"), ("NETWORK","◉")]:
            row = QHBoxLayout()
            row.addWidget(label(f"{icon} {name}", 8, C_DIM))
            pct = label("0%", 8, C_TEXT)
            self.bar_labels[name] = pct
            row.addWidget(pct)
            sys_layout.addLayout(row)
            bar = BarWidget(C_BLUE if name != "NETWORK" else C_GREEN)
            self.bars[name] = bar
            sys_layout.addWidget(bar)

        layout.addWidget(sys_frame)

        # Quick Access
        qa_frame = QFrame()
        qa_frame.setStyleSheet(panel_style())
        qa_layout = QVBoxLayout(qa_frame)
        qa_layout.setContentsMargins(8,8,8,8)
        qa_layout.setSpacing(2)
        qa_layout.addWidget(label("QUICK ACCESS", 8, C_BLUE, True))
        for name, cmd in [("📁 FILES","explorer"), ("🌐 BROWSER","start chrome"),
                           ("⚙ SETTINGS","start ms-settings:"), ("💻 TERMINAL","start cmd")]:
            btn = QPushButton(name)
            btn.setStyleSheet("""
                QPushButton { background: rgba(0,30,60,150); color: rgb(180,230,255);
                    border: 1px solid rgba(0,180,255,40); border-radius: 3px;
                    font-family: 'Courier New'; font-size: 9px; padding: 4px; text-align: left; }
                QPushButton:hover { background: rgba(0,60,100,200); border-color: rgba(0,180,255,120); }
            """)
            btn.clicked.connect(lambda _, c=cmd: os.system(c))
            qa_layout.addWidget(btn)
        layout.addWidget(qa_frame)

        # Upcoming Events (artik events.json'dan gercek veri okuyor)
        ev_frame = QFrame()
        ev_frame.setStyleSheet(panel_style())
        ev_layout = QVBoxLayout(ev_frame)
        ev_layout.setContentsMargins(8,8,8,8)
        ev_layout.setSpacing(3)
        head_row = QHBoxLayout()
        head_row.addWidget(label("UPCOMING EVENTS", 8, C_BLUE, True))
        add_btn = QPushButton("+")
        add_btn.setFixedSize(18, 18)
        add_btn.setStyleSheet("""
            QPushButton { background: rgba(0,60,100,180); color: rgb(0,220,255);
                border: 1px solid rgba(0,180,255,80); border-radius: 3px; font-weight:bold; }
            QPushButton:hover { background: rgba(0,100,160,220); }
        """)
        add_btn.clicked.connect(self._add_event_dialog)
        head_row.addWidget(add_btn)
        ev_layout.addLayout(head_row)
        self.event_labels = []
        for _ in range(4):
            l = label("—", 8, C_DIM)
            l.setWordWrap(True)
            ev_layout.addWidget(l)
            self.event_labels.append(l)
        layout.addWidget(ev_frame)
        self.refresh_events()

        # Weather
        wx_frame = QFrame()
        wx_frame.setStyleSheet(panel_style())
        wx_layout = QVBoxLayout(wx_frame)
        wx_layout.setContentsMargins(8,8,8,8)
        wx_layout.setSpacing(3)
        wx_layout.addWidget(label("WEATHER", 8, C_BLUE, True))
        self.wx_label = label("Fetching...", 9, C_TEXT)
        self.wx_label.setWordWrap(True)
        wx_layout.addWidget(self.wx_label)
        layout.addWidget(wx_frame)

        layout.addStretch()

        # Etkinlikleri periyodik yenile (baska yerden eklenmis olabilir)
        self._ev_timer = QTimer(self)
        self._ev_timer.timeout.connect(self.refresh_events)
        self._ev_timer.start(5000)

    def _add_event_dialog(self):
        from PyQt5.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Yeni Etkinlik", "Saat ve aciklama (orn: 18:00 Antrenman):")
        if ok and text.strip():
            events = load_json(EVENTS_FILE, [])
            events.append(text.strip())
            events = events[-20:]
            save_json(EVENTS_FILE, events)
            self.refresh_events()

    def refresh_events(self):
        events = load_json(EVENTS_FILE, [])
        for i, l in enumerate(self.event_labels):
            if i < len(events):
                l.setText("• " + events[-(i+1)])
                l.setStyleSheet(f"color: rgb({C_TEXT.red()},{C_TEXT.green()},{C_TEXT.blue()}); background: transparent;")
            else:
                l.setText("—")
                l.setStyleSheet(f"color: rgb({C_DIM.red()},{C_DIM.green()},{C_DIM.blue()}); background: transparent;")

    def update_stats(self, cpu, ram, disk, net, net_text=None):
        for name, val in [("CPU", cpu), ("RAM", ram), ("STORAGE", disk), ("NETWORK", min(100, net))]:
            self.bars[name].set_value(val)
            if name == "NETWORK" and net_text:
                self.bar_labels[name].setText(net_text)
            else:
                self.bar_labels[name].setText(f"{val:.0f}%")

    def set_weather(self, text):
        self.wx_label.setText(text)

# ══════════════════════════════════════════
#  Orta panel
# ══════════════════════════════════════════
class CenterPanel(QWidget):
    command_submitted = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Başlık
        title = label("J A R V I S", 22, C_BLUE, True)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Orb
        self.orb = IntelOrb()
        layout.addWidget(self.orb, alignment=Qt.AlignCenter)

        # Sohbet alanı
        chat_frame = QFrame()
        chat_frame.setStyleSheet(panel_style())
        chat_layout = QVBoxLayout(chat_frame)
        chat_layout.setContentsMargins(8,8,8,8)

        self.chat_area = QScrollArea()
        self.chat_area.setWidgetResizable(True)
        self.chat_area.setStyleSheet("background: transparent; border: none;")
        self.chat_area.setFixedHeight(140)

        self.chat_widget = QWidget()
        self.chat_widget.setStyleSheet("background: transparent;")
        self.chat_inner = QVBoxLayout(self.chat_widget)
        self.chat_inner.setContentsMargins(0,0,0,0)
        self.chat_inner.setSpacing(3)
        self.chat_inner.addStretch()
        self.chat_area.setWidget(self.chat_widget)
        chat_layout.addWidget(self.chat_area)

        # Input
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a command or ask anything...")
        self.input.setStyleSheet("""
            QLineEdit { background: rgba(0,20,40,180); color: rgb(0,220,255);
                border: 1px solid rgba(0,180,255,120); border-radius: 4px;
                font-family: 'Courier New'; font-size: 11px; padding: 6px; }
        """)
        self.input.returnPressed.connect(self._submit)

        mic_btn = QPushButton("🎤")
        mic_btn.setFixedSize(36, 36)
        mic_btn.setStyleSheet("""
            QPushButton { background: rgba(0,40,80,180); color: rgb(0,220,255);
                border: 1px solid rgba(0,180,255,80); border-radius: 4px; font-size: 14px; }
            QPushButton:hover { background: rgba(0,80,140,200); }
        """)

        send_btn = QPushButton("▶")
        send_btn.setFixedSize(36, 36)
        send_btn.setStyleSheet("""
            QPushButton { background: rgba(0,180,255,180); color: black;
                border: none; border-radius: 4px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: rgba(0,220,255,220); }
        """)
        send_btn.clicked.connect(self._submit)

        input_row.addWidget(self.input)
        input_row.addWidget(mic_btn)
        input_row.addWidget(send_btn)
        chat_layout.addLayout(input_row)
        layout.addWidget(chat_frame)

    def _submit(self):
        text = self.input.text().strip()
        if not text: return
        self.input.clear()
        self.add_message("You", text, C_GOLD)
        self.command_submitted.emit(text)

    def add_message(self, sender, text, color=C_TEXT):
        msg = label(f"{sender}: {text}", 9, color)
        msg.setWordWrap(True)
        self.chat_inner.addWidget(msg)
        QTimer.singleShot(50, lambda: self.chat_area.verticalScrollBar().setValue(
            self.chat_area.verticalScrollBar().maximum()))

    def set_speaking(self, v):
        self.orb.set_speaking(v)

# ══════════════════════════════════════════
#  Sağ panel
# ══════════════════════════════════════════
class RightPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # System Status
        st_frame = QFrame()
        st_frame.setStyleSheet(panel_style())
        st_layout = QVBoxLayout(st_frame)
        st_layout.setContentsMargins(8,8,8,8)
        st_layout.setSpacing(3)
        st_layout.addWidget(label("SYSTEM STATUS", 8, C_BLUE, True))
        self.status_dot = label("● ONLINE", 10, C_GREEN, True)
        st_layout.addWidget(self.status_dot)
        self.ai_label  = label("AI CORE : ACTIVE", 8, C_DIM)
        self.mem_label = label("MEMORY  : OPTIMAL", 8, C_DIM)
        st_layout.addWidget(self.ai_label)
        st_layout.addWidget(self.mem_label)
        layout.addWidget(st_frame)

        # Active Processing
        ap_frame = QFrame()
        ap_frame.setStyleSheet(panel_style())
        ap_layout = QVBoxLayout(ap_frame)
        ap_layout.setContentsMargins(8,8,8,8)
        ap_layout.setSpacing(4)
        ap_layout.addWidget(label("ACTIVE PROCESSING", 8, C_BLUE, True))
        self.proc_label = label("LISTENING", 10, C_BLUE, True)
        self.proc_label.setAlignment(Qt.AlignCenter)
        ap_layout.addWidget(self.proc_label)
        self.wave = WaveWidget()
        ap_layout.addWidget(self.wave)
        layout.addWidget(ap_frame)

        # Memory Stream (artik gercek/kalici son islem gecmisini gosterir)
        ms_frame = QFrame()
        ms_frame.setStyleSheet(panel_style())
        ms_layout = QVBoxLayout(ms_frame)
        ms_layout.setContentsMargins(8,8,8,8)
        ms_layout.setSpacing(2)
        ms_layout.addWidget(label("MEMORY STREAM", 8, C_BLUE, True))
        self.memory_labels = []
        for _ in range(5):
            l = label("—", 8, C_DIM)
            l.setWordWrap(True)
            ms_layout.addWidget(l)
            self.memory_labels.append(l)
        layout.addWidget(ms_frame)
        self.refresh_memory()

        self._mem_timer = QTimer(self)
        self._mem_timer.timeout.connect(self.refresh_memory)
        self._mem_timer.start(3000)

        # Neural Network
        nn_frame = QFrame()
        nn_frame.setStyleSheet(panel_style())
        nn_layout = QVBoxLayout(nn_frame)
        nn_layout.setContentsMargins(8,8,8,8)
        nn_layout.setSpacing(4)
        nn_layout.addWidget(label("NEURAL NETWORK", 8, C_BLUE, True))
        self.neural = NeuralWidget()
        nn_layout.addWidget(self.neural)
        layout.addWidget(nn_frame)

        # Tools (artik gercek islevlere bagli)
        tools_frame = QFrame()
        tools_frame.setStyleSheet(panel_style())
        tools_layout = QVBoxLayout(tools_frame)
        tools_layout.setContentsMargins(8,8,8,8)
        tools_layout.setSpacing(4)
        tools_layout.addWidget(label("TOOLS", 8, C_BLUE, True))
        tools_grid = QGridLayout()
        tools_grid.setSpacing(4)
        self.tool_actions = {
            "VOICE":    self._tool_voice,
            "CAMERA":   self._tool_camera,
            "SCREEN":   self._tool_screenshot,
            "EMAIL":    self._tool_email,
            "CALENDAR": self._tool_calendar,
            "NOTES":    self._tool_notes,
        }
        for i, (icon, name) in enumerate([("🎤","VOICE"),("📷","CAMERA"),("🖥","SCREEN"),
                                           ("📧","EMAIL"),("📅","CALENDAR"),("📝","NOTES")]):
            btn = QPushButton(f"{icon}\n{name}")
            btn.setFixedSize(52, 44)
            btn.setStyleSheet("""
                QPushButton { background: rgba(0,30,60,150); color: rgb(0,180,255);
                    border: 1px solid rgba(0,180,255,40); border-radius: 4px;
                    font-family: 'Courier New'; font-size: 7px; }
                QPushButton:hover { background: rgba(0,60,120,200); }
            """)
            btn.clicked.connect(lambda checked=False, n=name: self.tool_actions[n]())
            tools_grid.addWidget(btn, i//3, i%3)
        tools_layout.addLayout(tools_grid)
        layout.addWidget(tools_frame)

        layout.addStretch()

    # ---------------- MEMORY STREAM ----------------
    def refresh_memory(self):
        items = load_json(MEMORY_FILE, [])
        items = items[-5:][::-1]  # en yeni en ustte
        for i, l in enumerate(self.memory_labels):
            if i < len(items):
                l.setText(f"[{items[i]['time']}] {items[i]['text']}")
                l.setStyleSheet(f"color: rgb({C_TEXT.red()},{C_TEXT.green()},{C_TEXT.blue()}); background: transparent;")
            else:
                l.setText("—")
                l.setStyleSheet(f"color: rgb({C_DIM.red()},{C_DIM.green()},{C_DIM.blue()}); background: transparent;")

    def set_processing(self, text, active=False):
        self.proc_label.setText(text)
        self.wave.set_active(active)

    # ---------------- TOOLS ----------------
    def _tool_voice(self):
        try:
            import jarvis_voice
            jarvis_voice.active = not jarvis_voice.active
            state = "AKTIF" if jarvis_voice.active else "KAPALI"
            append_memory(f"Sesli dinleme {state} yapildi")
            self.refresh_memory()
        except Exception as e:
            append_memory(f"Ses araci hatasi: {e}")
            self.refresh_memory()

    def _tool_camera(self):
        try:
            if os.name == "nt":
                os.system("start microsoft.windows.camera:")
            append_memory("Kamera acildi")
        except Exception as e:
            append_memory(f"Kamera hatasi: {e}")
        self.refresh_memory()

    def _tool_screenshot(self):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            fname = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            path = os.path.join(DATA_DIR, fname)
            img.save(path)
            append_memory(f"Ekran goruntusu kaydedildi: {fname}")
        except ImportError:
            append_memory("Ekran goruntusu hatasi: Pillow kurulu degil (pip install pillow)")
        except Exception as e:
            append_memory(f"Ekran goruntusu hatasi: {e}")
        self.refresh_memory()

    def _tool_email(self):
        try:
            import webbrowser
            webbrowser.open("https://mail.google.com")
            append_memory("E-posta acildi")
        except Exception as e:
            append_memory(f"E-posta hatasi: {e}")
        self.refresh_memory()

    def _tool_calendar(self):
        try:
            import webbrowser
            webbrowser.open("https://calendar.google.com")
            append_memory("Takvim acildi")
        except Exception as e:
            append_memory(f"Takvim hatasi: {e}")
        self.refresh_memory()

    def _tool_notes(self):
        try:
            if os.name == "nt":
                os.system("notepad.exe")
            append_memory("Not defteri acildi")
        except Exception as e:
            append_memory(f"Not defteri hatasi: {e}")
        self.refresh_memory()

# ══════════════════════════════════════════
#  Top bar
# ══════════════════════════════════════════
class TopBar(QWidget):
    def __init__(self, close_cb):
        super().__init__()
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self.clock = label("00:00", 14, C_BLUE, True)
        self.date  = label("SATURDAY", 8, C_DIM)
        layout.addWidget(self.clock)
        layout.addWidget(self.date)
        layout.addStretch()

        center = label("J.A.R.V.I.S  v2.0", 10, C_BLUE, True)
        center.setAlignment(Qt.AlignCenter)
        layout.addWidget(center)
        layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton { background: rgba(255,50,50,150); color: white;
                border: none; border-radius: 4px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background: rgba(255,80,80,220); }
        """)
        close_btn.clicked.connect(close_cb)
        layout.addWidget(close_btn)

        t = QTimer(self)
        t.timeout.connect(self._update_clock)
        t.start(1000)
        self._update_clock()

    def _update_clock(self):
        now = datetime.datetime.now()
        self.clock.setText(now.strftime("%H:%M"))
        self.date.setText(now.strftime("%A  ·  %b %d, %Y").upper())

# ══════════════════════════════════════════
#  Dashboard ana pencere
# ══════════════════════════════════════════
class DashboardWindow(QMainWindow):
    response_received = pyqtSignal(str)   # JARVIS'in cevabi (diger thread'lerden guvenli)
    command_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S. Dashboard")
        self.setMinimumSize(720, 600)
        self.resize(900, 660)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag = None
        self._activity = []      # son komut/cevap zamanlari (neural icin)
        self._net_last = None    # (zaman, toplam bayt) -> hiz hesabi
        self._hooked = False

        central = QWidget()
        central.setStyleSheet("background: rgba(0,0,0,240); border: 1px solid rgba(0,180,255,80); border-radius: 8px;")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        self.topbar = TopBar(self.hide)
        root.addWidget(self.topbar)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(0,180,255,60);")
        root.addWidget(sep)

        # Main area
        main = QHBoxLayout()
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(8)

        self.left   = LeftPanel()
        self.center = CenterPanel()
        self.right  = RightPanel()

        main.addWidget(self.left)
        main.addWidget(self.center, 1)
        main.addWidget(self.right)
        root.addLayout(main)

        self.setCentralWidget(central)

        # Signals
        self.center.command_submitted.connect(self._on_command)
        self.response_received.connect(self._show_response)
        self.command_finished.connect(self._on_finished)
        self._hook_responses()

        # Stats timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(2000)
        self._update_stats()

        # Weather
        threading.Thread(target=self._fetch_weather, daemon=True).start()

    # ---- JARVIS'in gercek cevaplarini sohbete baglar (YAMA_UYGULANDI_v1) ----
    def _hook_responses(self, allow_import=False):
        if self._hooked:
            return
        try:
            mod = sys.modules.get("jarvis_voice")
            if mod is None and allow_import:
                import jarvis_voice as mod
            if mod is not None and hasattr(mod, "response_callbacks"):
                mod.response_callbacks.append(self.response_received.emit)
                self._hooked = True
        except Exception as e:
            print("Dashboard cevap baglantisi kurulamadi:", e)

    def _show_response(self, text):
        self._activity.append(time.time())
        self.center.add_message("JARVIS", text, C_BLUE)

    def _on_finished(self):
        self.right.set_processing("LISTENING", False)
        self.center.set_speaking(False)

    def _on_command(self, text):
        append_memory(f"Komut: {text}")
        self.right.refresh_memory()
        self._activity.append(time.time())
        try:
            self._hook_responses(allow_import=True)
            from jarvis_voice import process_command
            self.right.set_processing("PROCESSING", True)
            self.center.set_speaking(True)

            def _run():
                try:
                    process_command(text)
                finally:
                    self.command_finished.emit()
            threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            self.center.add_message("JARVIS", f"Error: {e}", QColor(255, 80, 80))

    def _update_stats(self):
        cpu  = psutil.cpu_percent()
        ram  = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent

        # NETWORK: toplam bayt yerine gercek anlik hiz (MB/s)
        net = psutil.net_io_counters()
        now_t = time.time()
        total = net.bytes_sent + net.bytes_recv
        speed = 0.0
        if self._net_last is not None:
            dt = now_t - self._net_last[0]
            if dt > 0:
                speed = max(0.0, (total - self._net_last[1]) / dt / 1024 / 1024)
        self._net_last = (now_t, total)
        net_pct = min(100.0, speed / NET_FULL_SCALE_MBPS * 100)
        self.left.update_stats(cpu, ram, disk, net_pct, f"{speed:.1f}MB/s")

        # NEURAL NETWORK: son 30 saniyedeki gercek komut/cevap sayisi
        self._activity = [t for t in self._activity if now_t - t < 30]
        activity = min(1.0, len(self._activity) / 5.0)
        self.right.neural.set_metrics(cpu, activity)

    def _fetch_weather(self):
        try:
            r = requests.get("https://wttr.in/?format=3", timeout=5)
            QTimer.singleShot(0, lambda: self.left.set_weather(r.text.strip()))
        except:
            QTimer.singleShot(0, lambda: self.left.set_weather("Unavailable"))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag:
            self.move(e.globalPos() - self._drag)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(0, 0, 0, 240)))
        p.setPen(QPen(QColor(0, 180, 255, 80), 1))
        p.drawRoundedRect(self.rect(), 8, 8)
        p.end()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = DashboardWindow()
    w.show()
    sys.exit(app.exec_())