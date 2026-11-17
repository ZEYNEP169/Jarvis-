# -*- coding: utf-8 -*-
"""
JARVIS DYNAMIC ISLAND
Ekranin ust ortasinda duran kucuk siyah "hap". Normalde ince bir centik,
bir sey olunca animasyonla buyur, is bitince tekrar kuculur.

Gosterdigi durumlar (oncelik sirasiyla):
  1) JARVIS konusuyor / telefondan bildirim geldi  -> yazi
  2) Mikrofona ses geliyor                         -> dalga
  3) Yeni sarki basladi                            -> sarki adi
  4) Hicbiri                                       -> kucuk centik

Bu dosya jarvis_voice.py'ye sadece "ekleme" yapar, mevcut kodu degistirmez.
Hata olursa JARVIS'in geri kalani calismaya devam eder.
"""

import os
import json
import math
import random
import time
import threading
from collections import deque

from PyQt5.QtCore import (Qt, QTimer, QRect, QRectF, QPropertyAnimation,
                          QEasingCurve, QObject, pyqtSignal, QPointF)
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QFont,
                         QFontMetrics, QPainterPath, QLinearGradient, QImage, QPixmap, QCursor)
from PyQt5.QtWidgets import QWidget, QApplication, QLineEdit, QLabel, QVBoxLayout, QPushButton

# gorev / not / takvim paneli icin veri katmani (yoksa ada yine de calisir)
try:
    import jarvis_panels as _panels
except Exception as _e:
    _panels = None
    print("Island: jarvis_panels yuklenemedi (sorun degil):", _e)

# sarki sozleri (yoksa soz butonu "soz bulunamadi" gosterir, ada yine de calisir)
try:
    import jarvis_lyrics as _lyrics
except Exception as _e:
    _lyrics = None
    print("Island: jarvis_lyrics yuklenemedi (sorun degil):", _e)

# ── Ayarlar (istedigin gibi degistirebilirsin) ──
IDLE_W, IDLE_H = 120, 28          # normal centik boyutu
TOP_MARGIN = 6                    # ekranin ustunden bosluk
MAX_W = 560                       # yazi modunda en genis hali
VOICE_W, VOICE_H = 260, 44        # dalga modu boyutu
MUSIC_W, MUSIC_H = 420, 44
MASCOT_W, MASCOT_H = 300, 120    # maskot modu boyutu
MASCOT_HOLD_MS = 1500            # fare cekilince maskot kac ms daha kalsin        # sarki modu boyutu
VOICE_THRESHOLD = 0.15            # bu seviyenin ustu "ses var" sayilir (0..1)
VOICE_HOLD = 1.2                  # ses kesilince dalga kac saniye daha kalsin
MUSIC_SHOW_MS = 4000              # sarki adi kac ms gorunsun
HIDE_ON_FULLSCREEN = True        # tam ekran film/oyun varken ada gizlensin (False: hep gorunsun)
SPEECH_END_HOLD_MS = 2500        # konusma bitince ada kac ms daha acik kalsin
MAX_CHARS = 900                   # cok uzun cevaplar kesilsin
MAX_TEXT_H = 380                  # yazi alaninin en fazla yuksekligi (px)

PANEL_W = 380                     # panel (gorev/not/takvim) genisligi
PANEL_HEAD = 40                   # sekme cubugu yuksekligi
ROW_H = 26                        # satir yuksekligi
PANEL_HOLD_MS = 8000              # panel kac ms acik kalsin (fare uzerindeyken kapanmaz)
PANEL_LEAVE_MS = 3000             # fare cekilince panel kac ms daha kalsin

LYRICS_W, LYRICS_H = 560, 150     # soz modu boyutu
LYR_LEFT_W = 244                  # soz modunda sol sutun (baslik, sure, dugmeler) genisligi
LYRICS_LEAD = 0.25                # sozu bu kadar sn erken goster (ekran gecikmesini telafi eder)
LYRICS_LEAVE_MS = 2500            # fare cekilince soz modu kac ms daha kalsin
PANEL_INPUT_H = 40                # alttaki yazma satirinin kapladigi yukseklik
# Sekmeler: (anahtar, baslik, genislik). Yeni sekme eklemek icin buraya satir ekle.
_TABS = (("tasks", "GÖREV", 86), ("notes", "NOT", 66), ("clips", "PANO", 74))
_TYPE_TABS = ("tasks", "notes")   # yazma satirinin gorundugu sekmeler

CYAN = QColor(0, 210, 255)
AMBER = QColor(255, 190, 0)
BODY = QColor(5, 8, 14, 245)

_instance = None
_phone_texts = set()
_gesture_toggle_cb = None   # jarvis_voice: el modunu ac/kapat (dugme icin)
_preview_cb = None          # jarvis_voice: kamera onizlemesi acildi/kapandi
_phone_cb = None            # jarvis_voice: telefon ekranini goster (dugme icin)


class _Bridge(QObject):
    # Baska thread'lerden (speak, telefon dinleyicisi) guvenle yazi yollamak icin
    show_text = pyqtSignal(str, str)   # tur, yazi
    speech_end = pyqtSignal()           # konusma bitti
    show_panel = pyqtSignal(str)        # 'tasks' | 'notes' | 'clips'
    gesture_state = pyqtSignal(bool)    # el modu acildi / kapandi
    react = pyqtSignal(str, str)        # hareket adi, yazi (maskot tepkisi)
    hud_level = pyqtSignal(float)       # jarvis_hud seviyesi (0..1), dunya buyutme hareketi
    hud_hide = pyqtSignal()             # jarvis_hud'i kapat
    cam_show = pyqtSignal(bool)         # canli kamera penceresini ac / kapat
    cam_frame = pyqtSignal(object)      # (QImage, yazi)


def notify(text, kind="speak"):
    """Herhangi bir thread'den cagrilabilir. Adada yazi gosterir."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.show_text.emit(kind, str(text))
    except Exception:
        pass


def speech_done():
    """Herhangi bir thread'den cagrilabilir: JARVIS konusmayi bitirdi, ada az sonra kapansin."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.speech_end.emit()
    except Exception:
        pass


def show_panel(tab="tasks"):
    """Herhangi bir thread'den cagrilabilir: adada gorev/not/takvim panelini acar."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.show_panel.emit(str(tab))
    except Exception:
        pass


def set_gesture(on):
    """Herhangi bir thread'den cagrilabilir: el modu acikken adada kucuk kamera gostergesi cikar."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.gesture_state.emit(bool(on))
    except Exception:
        pass


def hud_set_level(level):
    """Herhangi bir thread'den cagrilabilir: holografik harita HUD'unun buyuklugunu ayarlar (0..1)."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.hud_level.emit(float(level))
    except Exception:
        pass


def hud_close():
    """Herhangi bir thread'den cagrilabilir: HUD'u yumusakca kapatir."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.hud_hide.emit()
    except Exception:
        pass


def react(name, label=""):
    """Herhangi bir thread'den cagrilabilir: maskot el hareketine tepki verir (dans, flas...)."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.react.emit(str(name), str(label))
    except Exception:
        pass


def show_camera(on):
    """Herhangi bir thread'den cagrilabilir: canli kamera penceresini acar / kapatir."""
    inst = _instance
    if inst is None:
        return
    try:
        inst._bridge.cam_show.emit(bool(on))
    except Exception:
        pass


def push_frame(data, w, h, info=""):
    """Herhangi bir thread'den cagrilabilir: kamera karesi (RGB bayt dizisi) onizleme penceresine gider."""
    inst = _instance
    if inst is None:
        return
    try:
        img = QImage(data, int(w), int(h), int(w) * 3, QImage.Format_RGB888).copy()
        inst._bridge.cam_frame.emit((img, str(info)))
    except Exception:
        pass


class CameraWindow(QWidget):
    """Canli kamera onizlemesi: el iskeleti + algilanan hareket. X ile kapatinca sadece onizleme kapanir,
    el modu acik kalir (kapatmak icin el dugmesine bas ya da 'el modu kapat' de)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS - El modu")
        # her zaman ustte DEGIL: baska bir uygulamayi acinca pencere arkada kalir
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_pos)
        self.setStyleSheet("background: #05080E; color: #EBF5FF;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self._is_fs = False
        self._pre_fs_geom = None
        self._win_size = (192, 144)       # normal (kucuk) boyut, tam ekrandan cikinca buna donulur
        self.view = QLabel("Kamera açılıyor…")
        self.view.setFixedSize(*self._win_size)
        self.view.setScaledContents(True)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setCursor(Qt.PointingHandCursor)
        self.view.mouseDoubleClickEvent = lambda e: self._toggle_fullscreen()
        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setStyleSheet("color: #00B4FF; font: bold 8pt 'Segoe UI';")
        lay.addWidget(self.view, 0, Qt.AlignHCenter)
        lay.addWidget(self.info)

        # tam ekran dugmesi: goruntuyu ekrani kaplayacak sekilde buyutur/kucultur (cift tiklama da ayni isi yapar)
        self.fs_btn = QPushButton("⛶  Tam ekran")
        self.fs_btn.setCursor(Qt.PointingHandCursor)
        self.fs_btn.setStyleSheet(
            "QPushButton { background: rgba(0,180,255,40); color: #9FDFFF; border: 1px solid rgba(0,180,255,90); "
            "border-radius: 4px; padding: 2px 6px; font: 8pt \'Segoe UI\'; } "
            "QPushButton:hover { background: rgba(0,180,255,90); }")
        self.fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(self.fs_btn)

        # hareket ipuclari: "Hareketler" dugmesiyle acilir / kapanir (tercih hatirlanir)
        self.help_btn = QPushButton()
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setStyleSheet(
            "QPushButton { background: rgba(0,180,255,40); color: #9FDFFF; border: 1px solid rgba(0,180,255,90); "
            "border-radius: 4px; padding: 2px 6px; font: 8pt 'Segoe UI'; } "
            "QPushButton:hover { background: rgba(0,180,255,90); }")
        self.help_btn.clicked.connect(self._toggle_help)
        self.help = QLabel(self._help_html())
        self.help.setTextFormat(Qt.RichText)
        self.help.setStyleSheet("color: #CFE9FF; font: 8pt 'Segoe UI', 'Segoe UI Emoji';")
        lay.addWidget(self.help_btn)
        lay.addWidget(self.help)
        self._help_on = bool(self._read_cfg().get("help", True))
        self._apply_help()

    def _toggle_fullscreen(self):
        """Kamera goruntusunu ekrani kaplayacak sekilde buyutur. Tekrar cagrilinca (ya da Esc) eski kucuk
        boyuta doner. Cift tiklama da ayni isi yapar."""
        if not self._is_fs:
            self._pre_fs_geom = self.geometry()
            sc = QApplication.primaryScreen().availableGeometry()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.view.setFixedSize(sc.width() - 48, sc.height() - 150)
            self.fs_btn.setText("⛶  Küçült (Esc)")
            self.adjustSize()
            self.move(sc.topLeft())
            self.resize(sc.size())
            self._is_fs = True
        else:
            self.view.setFixedSize(*self._win_size)
            self.fs_btn.setText("⛶  Tam ekran")
            self._is_fs = False
            self._apply_help()
            if self._pre_fs_geom is not None:
                self.setGeometry(self._pre_fs_geom)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self._is_fs:
            self._toggle_fullscreen()
        else:
            super().keyPressEvent(e)

    @staticmethod
    def _help_html():
        try:
            from jarvis_gesture import HELP_LINES, HELP_NOTE
        except Exception:
            return ""
        rows = "".join(
            f"<tr><td style='padding-right:6px'>{ic}</td><td style='padding-right:8px'><b>{name}</b></td>"
            f"<td style='color:#00B4FF'>{what}</td></tr>" for ic, name, what in HELP_LINES)
        return f"<table cellspacing='1'>{rows}</table><div style='color:#7FA8C4; margin-top:3px'>{HELP_NOTE}</div>"

    def _apply_help(self):
        has = bool(self.help.text())
        self.help_btn.setVisible(has)
        self.help.setVisible(has and self._help_on)
        self.help_btn.setText("Hareketler  ▴" if self._help_on else "Hareketler  ▾")
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def _toggle_help(self):
        self._help_on = not self._help_on
        self._apply_help()
        self._save_pos()

    def _read_cfg(self):
        try:
            with open(self._POS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    _POS_FILE = os.path.join("C:\\Jarvis" if os.name == "nt" else os.path.expanduser("~/.jarvis"), "camera_pos.json")

    def load_pos(self):
        """Son birakilan yeri hatirlar. Kayit yoksa ya da ekran disindaysa False doner."""
        try:
            with open(self._POS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            x, y = int(d["x"]), int(d["y"])
            for sc in QApplication.screens():
                if sc.availableGeometry().contains(x + 20, y + 20):
                    self.move(x, y)
                    return True
        except Exception:
            pass
        return False

    def _save_pos(self):
        try:
            with open(self._POS_FILE, "w", encoding="utf-8") as f:
                json.dump({"x": self.x(), "y": self.y(), "help": self._help_on}, f)
        except Exception:
            pass

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.isVisible():
            self._save_timer.start(600)    # surukleme bitince kaydet

    def set_frame(self, payload):
        img, info = payload
        self.view.setPixmap(QPixmap.fromImage(img))
        self.info.setText(info)

    def closeEvent(self, e):
        if _preview_cb:
            try:
                _preview_cb(False)
            except Exception:
                pass
        super().closeEvent(e)


def mark_phone(text):
    """phone_listener konusmadan hemen once cagirir; ada o yaziyi
    'telefon' rengiyle gosterir."""
    _phone_texts.add(str(text))


def _fullscreen_app_active():
    """Ana monitorde tam ekran bir uygulama (film, oyun, F11 tarayici) on planda mi?
    Sadece Windows'ta calisir; hata olursa False doner (ada gorunur kalir)."""
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False   # masaustu ve gorev cubugu tam ekran sayilmaz
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        hmon = user32.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        if r.left != 0 or r.top != 0:
            return False   # ana monitor degil, ada orada degil
        return (rect.left <= r.left and rect.top <= r.top and
                rect.right >= r.right and rect.bottom >= r.bottom)
    except Exception:
        return False


def _media_cmd(cmd):
    """Windows medya oturumuna (Spotify, tarayici...) komut yollar.
    cmd: 'toggle' | 'next' | 'prev'"""
    def run():
        try:
            import asyncio
            from winsdk.windows.media.control import \
                GlobalSystemMediaTransportControlsSessionManager as M

            async def go():
                s = (await M.request_async()).get_current_session()
                if not s:
                    return
                if cmd == "toggle":
                    await s.try_toggle_play_pause_async()
                elif cmd == "next":
                    await s.try_skip_next_async()
                elif cmd == "prev":
                    await s.try_skip_previous_async()
            asyncio.run(go())
        except Exception as e:
            print("Island medya hata:", e)
    threading.Thread(target=run, daemon=True).start()


class _PanelInput(QLineEdit):
    """Panelin altindaki yazma satiri. Tiklaninca pencereyi etkinlestirir (klavye odagi icin)."""
    lost = pyqtSignal()
    escaped = pyqtSignal()

    def mousePressEvent(self, e):
        try:
            self.window().activateWindow()
            self.setFocus(Qt.MouseFocusReason)
        except Exception:
            pass
        super().mousePressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.lost.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(e)


class IslandWidget(QWidget):
    def __init__(self, music_getter=None, media_getter=None):
        super().__init__()
        global _instance
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._music_getter = music_getter
        self._media_getter = media_getter   # {'title','artist','position','duration','playing'} dondurur
        self._mode = "idle"
        self._kind = "speak"
        self._text = ""
        self._music_title = ""
        self._old_title = ""
        self._slide = 1.0
        self._last_music = None
        self._music_on = False
        self._levels = deque([0.0] * 28, maxlen=28)
        self._level = 0.0
        self._last_voice = 0.0
        self._phase = 0.0
        self._font = QFont("Segoe UI", 10)
        # gozler (bosta)
        self._eye_last = 0.0
        self._eye_blink = None
        self._eye_next_blink = time.time() + 2.0
        self._eye_look = (0.0, 0.0)
        self._eye_target = (0.0, 0.0)
        self._eye_next_look = time.time() + 1.5
        # sarki bilgisi / sozler
        self._gesture_on = False
        self._media = None
        self._media_t = 0.0
        self._lyr_state = ("loading", [])
        self._lyr_idx = -2
        self._lyr_change = 0.0
        self._lyr_check = 0.0

        # maskot (jarvis_mascot.py varsa): fareyle uzerine gelince gorunur
        self._mascot = None
        try:
            from jarvis_mascot import JarvisMascot
            m = JarvisMascot(self)
            m._draw_card = False
            m.setAttribute(Qt.WA_TransparentForMouseEvents)
            m.setFixedSize(170, 120)
            m._look_gain = 2.6            # kucuk boyutta bakis daha belli olsun
            m._bounce_gain = 2.0          # ziplama daha yuksek olsun
            m._look_interval = (1.2, 2.8)  # daha sik etrafa baksin
            m.hide()
            self._mascot = m
            print("Island: maskot hazir")
        except Exception as e:
            print("Island: maskot yuklenemedi (sorun degil):", e)

        self._bridge = _Bridge()
        self._bridge.show_text.connect(self._on_text)
        self._bridge.speech_end.connect(self._on_speech_end)
        self._speaking = False
        self._bridge.show_panel.connect(self._open_panel)
        self._bridge.gesture_state.connect(self._on_gesture_state)
        self._bridge.react.connect(self._on_react)
        self._bridge.hud_level.connect(self._on_hud_level)
        self._bridge.hud_hide.connect(self._on_hud_hide)
        self._last_cursor = None
        self._cursor_moved = 0.0
        self._follow = None          # fare takibi: (nx, ny) -1..1 ya da None
        self._react_id = 0
        self._bridge.cam_show.connect(self._on_cam_show)
        self._bridge.cam_frame.connect(self._on_cam_frame)
        self._cam = None
        self._tab = "tasks"
        self._rows = []
        self._extra = 0
        self._empty = ""
        self._counts = {}
        self._clip_flash = 0.0           # 'kopyalandi' geri bildirimi bitis zamani
        self._clip_flash_row = -1
        try:
            QApplication.clipboard().dataChanged.connect(self._on_clipboard)
        except Exception as _e:
            print("Island: pano izlenemedi:", _e)
        self._input = _PanelInput(self)
        self._input.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,16); color: #EBF5FF; "
            "border: 1px solid rgba(0,180,255,100); border-radius: 13px; padding: 2px 12px; "
            "font-family: 'Segoe UI'; font-size: 10pt; selection-background-color: rgba(0,180,255,120); } "
            "QLineEdit:focus { border: 1px solid rgba(255,190,0,190); }")
        self._input.hide()
        self._input.returnPressed.connect(self._submit_input)
        self._input.lost.connect(self._on_input_lost)
        self._input.escaped.connect(self._on_input_escape)

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(340)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._to_idle)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(33)

        self._music_timer = QTimer(self)
        self._music_timer.timeout.connect(self._poll_music)
        self._music_timer.start(1000)

        self._fs_timer = QTimer(self)
        self._fs_timer.timeout.connect(self._check_fullscreen)
        self._fs_timer.start(1000)

        self._set_mode("idle", animate=False)
        _instance = self
        self.show()

    def _check_fullscreen(self):
        if not HIDE_ON_FULLSCREEN:
            return
        fs = _fullscreen_app_active()
        if fs and self.isVisible():
            self.hide()
        elif not fs and not self.isVisible():
            self._set_mode("idle", animate=False)
            self.show()

    # ── disaridan cagrilan ──
    def set_level(self, level):
        # mikrofon seviyesi (0..1). Pik degeri tutariz, tick yavasca dusurur.
        try:
            self._level = max(self._level, float(level))
        except Exception:
            pass

    # ── boyut / konum ──
    def _size_for(self, mode):
        if mode == "voice":
            return VOICE_W, VOICE_H
        if mode == "music":
            return MUSIC_W, MUSIC_H
        if mode == "text":
            return self._text_size()
        if mode == "mascot":
            return MASCOT_W, MASCOT_H
        if mode == "panel":
            return self._panel_size()
        if mode == "lyrics":
            return LYRICS_W, LYRICS_H
        return IDLE_W, IDLE_H

    def _mascot_speaks(self):
        # JARVIS konusurken solda maskot gorunsun mu?
        return self._mascot is not None and self._kind == "speak"

    def _text_left(self):
        return 90 if self._mascot_speaks() else 38

    def _text_size(self):
        fm = QFontMetrics(self._font)
        pad = self._text_left() + 18
        inner = MAX_W - pad
        r = fm.boundingRect(QRect(0, 0, inner, 2000),
                            Qt.TextWordWrap | Qt.AlignLeft, self._text)
        w = max(260 if self._mascot_speaks() else 200, min(MAX_W, r.width() + pad))
        # genislik secildikten sonra yuksekligi tekrar hesapla
        r = fm.boundingRect(QRect(0, 0, w - pad, 2000),
                            Qt.TextWordWrap | Qt.AlignLeft, self._text)
        h = min(r.height(), MAX_TEXT_H) + 24
        return w, max(80 if self._mascot_speaks() else 44, h)

    def _rect_for(self, w, h):
        scr = QApplication.primaryScreen().geometry()
        return QRect(scr.x() + (scr.width() - w) // 2, scr.y() + TOP_MARGIN, w, h)

    def _set_mode(self, mode, animate=True):
        old_w = self.width()
        self._mode = mode
        w, h = self._size_for(mode)
        rect = self._rect_for(w, h)
        if animate and self.isVisible():
            curve = QEasingCurve(QEasingCurve.OutBack if w >= old_w else QEasingCurve.InOutCubic)
            if w >= old_w:
                curve.setOvershoot(0.9)
            self._anim.stop()
            self._anim.setEasingCurve(curve)
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(rect)
            self._anim.start()
        else:
            self.setGeometry(rect)
        if self._mascot is not None:
            if mode == "mascot":
                self._mascot.setFixedSize(170, 120)
                self._mascot.set_status("idle")
                if not self._mascot.isVisible():
                    self._mascot.show()
                    QTimer.singleShot(250, self._mascot.wave)
            elif mode == "text" and self._kind == "speak":
                # JARVIS konusuyor: solda kucuk maskot, zipliyor, altin parilti
                self._mascot.setFixedSize(80, 80)
                self._mascot.set_status("speaking")
                self._mascot.show()
            else:
                self._mascot.hide()
                self._mascot.set_status("idle")
            self._place_mascot()
        self._sync_input()
        self.update()

    # ── gorev / not / takvim paneli ──
    def _panel_size(self):
        n = max(1, len(self._rows))
        tail = PANEL_INPUT_H if self._tab in _TYPE_TABS else 10
        return PANEL_W, PANEL_HEAD + n * ROW_H + (18 if self._extra else 0) + tail

    def _tab_rects(self):
        xs = 14.0
        out = []
        for _k, _n, w in _TABS:
            out.append(QRectF(xs, 8.0, float(w), 24.0))
            xs += w + 6.0
        return out

    def _close_rect(self):
        return QRectF(float(self.width()) - 14 - 24, 8.0, 24.0, 24.0)

    def _mascot_btn_rects(self):
        s, gap = 20.0, 4.0   # 5 dugme maskot yuksekligine (120) sigsin
        h = float(self.height())
        x = float(self.width()) - 14 - s
        n = len(_TABS) + (1 if _gesture_toggle_cb is not None else 0) + (1 if _phone_cb is not None else 0)
        y0 = (h - (n * s + (n - 1) * gap)) / 2.0
        return [QRectF(x, y0 + i * (s + gap), s, s) for i in range(n)]

    def _extra_btn_keys(self):
        """_mascot_btn_rects'teki sekme dugmelerinden SONRA gelen ekstra dugmeler, sirayla."""
        keys = []
        if _gesture_toggle_cb is not None:
            keys.append("hand")
        if _phone_cb is not None:
            keys.append("phone")
        return keys

    # ── pano gecmisi ──
    def _on_clipboard(self):
        if _panels is None:
            return
        try:
            cb = QApplication.clipboard()
            md = cb.mimeData()
            if md is None or not md.hasText():
                return
            # sifre yoneticileri 'gizli' isaretli kopyalar yollar: bunlari asla kaydetme
            for fmt in ("ExcludeClipboardContentFromMonitorProcessing",
                        "x-kde-passwordManagerHint"):
                if md.hasFormat(fmt):
                    return
            if getattr(self, "_clip_self", False):   # adanin kendi kopyasi: listeyi karistirma
                self._clip_self = False
                return
            if _panels.clip_add(md.text()) and self._mode == "panel" and self._tab == "clips":
                self._refresh_panel(force=True)
        except Exception as ex:
            print("Island pano hata:", ex)

    def _copy_clip(self, i):
        text = _panels.clip_get(i)
        if text is None:
            return
        self._clip_self = True
        QApplication.clipboard().setText(text)
        self._clip_flash = time.time() + 1.1
        self._clip_flash_row = i

    def _sync_input(self):
        show = (self._mode == "panel" and self._tab in _TYPE_TABS and _panels is not None)
        if show:
            self._input.setPlaceholderText(
                "Görev yaz, Enter'a bas…" if self._tab == "tasks" else "Not yaz, Enter'a bas…")
            self._input.setGeometry(14, self.height() - 36, max(40, self.width() - 28), 28)
            if not self._input.isVisible():
                self._input.show()
            self._input.raise_()
        elif self._input.isVisible():
            self._input.clearFocus()
            self._input.hide()

    def _submit_input(self):
        text = self._input.text().strip()
        if not text or _panels is None:
            return
        try:
            text = _panels.cap(text)
            if self._tab == "tasks":
                _panels.add_task(text)
            elif self._tab == "notes":
                _panels.add_note(text)
        except Exception as ex:
            print("Island ekleme hata:", ex)
        self._input.clear()
        self._refresh_panel(force=True)

    def _on_input_lost(self):
        if self._mode == "panel" and not self.underMouse():
            self._hold.start(PANEL_LEAVE_MS)

    def _on_input_escape(self):
        self._input.clearFocus()
        self._hold.stop()
        self._set_mode("idle")

    def _keep_panel(self):
        if self.underMouse() or self._input.hasFocus():
            self._hold.stop()
        else:
            self._hold.start(PANEL_HOLD_MS)

    def _refresh_panel(self, force=False):
        if _panels is None:
            return
        try:
            rows, extra, empty = _panels.rows_for(self._tab)
            counts = _panels.counts()
        except Exception as e:
            print("Island panel veri hatasi:", e)
            return
        changed = force or rows != self._rows or extra != self._extra
        self._rows, self._extra, self._empty, self._counts = rows, extra, empty, counts
        self._sync_input()
        if self._mode == "panel":
            if changed and self._panel_size() != (self.width(), self.height()):
                self._set_mode("panel")
            self.update()

    def _open_panel(self, tab="tasks"):
        if _panels is None:
            return
        self._tab = tab if tab in [k for k, _n, _w in _TABS] else "tasks"
        self._refresh_panel(force=True)
        self._set_mode("panel")
        self._keep_panel()

    def _place_mascot(self):
        m = self._mascot
        if m is None:
            return
        if self._mode == "text":
            m.move(6, (self.height() - m.height()) // 2)
        else:
            m.move((self.width() - m.width()) // 2, (self.height() - m.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_mascot()
        if getattr(self, "_input", None) is not None:
            self._sync_input()

    def _to_idle(self):
        if self._mode == "panel" and (self._input.hasFocus() or self.underMouse()):
            self._hold.start(PANEL_HOLD_MS)   # yazarken / fare ustundeyken kapanma
            return
        self._set_mode("idle")

    # ── fare: uzerine gelince kontroller, tiklayinca komut ──
    def enterEvent(self, e):
        if self._mode == "idle":
            if self._mascot is None:
                if not self._music_title:
                    self._music_title = "Müzik"
                self._set_mode("music")
            else:
                self._set_mode("mascot")
        if self._mode in ("music", "mascot", "panel", "lyrics"):
            self._hold.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._mode == "music":
            self._hold.start(1200)
        elif self._mode == "mascot":
            self._hold.start(MASCOT_HOLD_MS)
        elif self._mode == "panel" and not self._input.hasFocus():
            self._hold.start(PANEL_LEAVE_MS)
        elif self._mode == "lyrics":
            self._hold.start(LYRICS_LEAVE_MS)
        super().leaveEvent(e)

    def _btn_rects(self):
        # sirayla: soz, onceki, oynat/durdur, sonraki
        bw, bh, gap = 30.0, 30.0, 4.0
        w, h = float(self.width()), float(self.height())
        x0 = w - 14 - 4 * bw - 3 * gap
        y0 = (h - bh) / 2.0
        return [QRectF(x0 + i * (bw + gap), y0, bw, bh) for i in range(4)]

    def _lyr_btn_rects(self):
        bw, gap = 30.0, 6.0
        x0 = 18.0 + (LYR_LEFT_W - (4 * bw + 3 * gap)) / 2.0
        y0 = float(self.height()) - 14.0 - bw
        return [QRectF(x0 + i * (bw + gap), y0, bw, bw) for i in range(4)]

    # ── sarki bilgisi / sozler ──
    def _media_pos(self):
        """(su anki konum sn, toplam sure sn). Calarken son olcumden itibaren ilerletilir."""
        m = self._media
        if not m:
            return 0.0, 0.0
        pos = float(m.get("position") or 0.0)
        if m.get("playing"):
            pos += time.time() - self._media_t
        dur = float(m.get("duration") or 0.0)
        if dur > 0:
            pos = min(pos, dur)
        return max(0.0, pos), dur

    def _toggle_local(self):
        # oynat/durdur'a basinca ilerleme cubugu hemen donsun / ilerlesin (sonraki olcume kadar)
        m = self._media
        if m:
            pos, _d = self._media_pos()
            m["position"] = pos
            m["playing"] = not m.get("playing")
            self._media_t = time.time()
        self._music_on = not self._music_on

    def _refresh_lyrics(self):
        m = self._media
        if _lyrics is None or not m:
            self._lyr_state = ("none", [])
            return
        try:
            self._lyr_state = _lyrics.lookup(m.get("title", ""), m.get("artist", ""),
                                             m.get("duration", 0.0))
        except Exception as ex:
            print("Island soz hata:", ex)
            self._lyr_state = ("none", [])

    def _open_lyrics(self):
        self._lyr_idx = -2
        self._lyr_check = 0.0
        self._lyr_state = ("loading", [])
        self._refresh_lyrics()
        self._set_mode("lyrics")
        self._hold.stop()

    @staticmethod
    def _fmt_time(sec):
        sec = max(0, int(sec))
        return "%02d:%02d" % (sec // 60, sec % 60)

    def mousePressEvent(self, e):
        if self._mode == "panel":
            if self._tab == "clips" and _panels is not None and e.button() in (Qt.LeftButton, Qt.RightButton):
                px, py = float(e.pos().x()), float(e.pos().y())
                if py >= PANEL_HEAD and not self._close_rect().contains(px, py):
                    i = int((py - PANEL_HEAD) // ROW_H)
                    if 0 <= i < len(self._rows):
                        if e.button() == Qt.RightButton:
                            _panels.clip_remove(i)
                            self._refresh_panel(force=True)
                        else:
                            self._copy_clip(i)
                            self.update()
                        self._keep_panel()
                        return
            if e.button() == Qt.LeftButton:
                x, y = float(e.pos().x()), float(e.pos().y())
                for key, rect in zip([k for k, _n, _w in _TABS], self._tab_rects()):
                    if rect.contains(x, y):
                        self._tab = key
                        self._refresh_panel(force=True)
                        self._keep_panel()
                        return
                if self._close_rect().contains(x, y):
                    self._hold.stop()
                    self._set_mode("idle")
                    return
                if self._tab == "tasks" and _panels is not None and y >= PANEL_HEAD:
                    i = int((y - PANEL_HEAD) // ROW_H)
                    if 0 <= i < len(self._rows):
                        try:
                            _panels.toggle_task(i)
                        except Exception as ex:
                            print("Island gorev hata:", ex)
                        self._refresh_panel(force=True)
                        self._keep_panel()
            return
        if self._mode == "lyrics":
            if e.button() in (Qt.LeftButton, Qt.RightButton):
                x, y = float(e.pos().x()), float(e.pos().y())
                for rect, cmd in zip(self._lyr_btn_rects(), ("lyrics", "prev", "toggle", "next")):
                    if rect.contains(x, y):
                        if cmd == "lyrics":
                            self._set_mode("music")      # sozleri kapat: sarki cubuguna don
                        else:
                            _media_cmd(cmd)
                            if cmd == "toggle":
                                self._toggle_local()
                        return
            return
        if self._mode == "mascot" and self._mascot is not None:
            if e.button() == Qt.LeftButton:
                x, y = float(e.pos().x()), float(e.pos().y())
                rects = self._mascot_btn_rects()
                for key, rect in zip([k for k, _n, _w in _TABS], rects):
                    if rect.contains(x, y):
                        self._open_panel(key)
                        return
                n_tabs = len(_TABS)
                for off, key in enumerate(self._extra_btn_keys()):
                    if rects[n_tabs + off].contains(x, y):
                        if key == "hand":
                            self._toggle_hand()
                        else:
                            self._open_phone()
                        return
            try:
                self._mascot._bounce_start = self._mascot._now()
            except Exception:
                pass
            # SAG tik: muzik kontrollerine gec (sol tik sadece ziplatir)
            if e.button() == Qt.RightButton:
                if not self._music_title:
                    self._music_title = "Müzik"
                self._slide = 1.0
                self._set_mode("music")
                self._hold.stop()
            return
        if self._mode == "music" and e.button() in (Qt.LeftButton, Qt.RightButton):
            pt = e.pos()
            for rect, cmd in zip(self._btn_rects(), ("lyrics", "prev", "toggle", "next")):
                if rect.contains(float(pt.x()), float(pt.y())):
                    if cmd == "lyrics":
                        self._open_lyrics()
                        return
                    _media_cmd(cmd)
                    if cmd == "toggle":
                        self._toggle_local()
                    self._hold.start(MUSIC_SHOW_MS)
                    return
            # duğme dışına tıkla: maskota geri dön
            if self._mascot is not None:
                self._set_mode("mascot")
                self._hold.stop()
                return
        super().mousePressEvent(e)

    # ── olaylar ──
    def _on_text(self, kind, text):
        text = (text or "").strip()
        if not text:
            return
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rstrip() + "…"
        if text in _phone_texts:
            _phone_texts.discard(text)
            kind = "phone"
        self._kind = kind
        self._text = text
        self._set_mode("text")
        if kind == "speak":
            # Konusma bitene kadar acik kal (bitince speech_done kapatma sayacini baslatir).
            # 3 dk'lik emniyet sayaci: bitis sinyali hic gelmezse ada takili kalmasin.
            self._speaking = True
            self._hold.start(180000)
        else:
            self._speaking = False
            self._hold.start(1600 if kind == "gesture" else max(3500, len(text) * 85))

    def _on_gesture_state(self, on):
        self._gesture_on = bool(on)
        self.update()

    def _on_cam_show(self, on):
        if on:
            if self._cam is None:
                self._cam = CameraWindow()
            if not self._cam.isVisible() and not self._cam.load_pos():
                sc = QApplication.primaryScreen().availableGeometry()
                self._cam.move(sc.left() + 12, sc.bottom() - self._cam.height() - 12)   # ilk acilis: sol alt kose
            self._cam.show()
        elif self._cam is not None:
            self._cam.hide()

    def _on_cam_frame(self, payload):
        if self._cam is not None and self._cam.isVisible():
            self._cam.set_frame(payload)

    def _toggle_hand(self):
        cb = _gesture_toggle_cb
        if cb:
            threading.Thread(target=cb, daemon=True).start()

    def _open_phone(self):
        cb = _phone_cb
        if cb:
            threading.Thread(target=cb, daemon=True).start()

    def _on_speech_end(self):
        self._speaking = False
        if self._mode == "text" and self._kind == "speak":
            self._hold.start(SPEECH_END_HOLD_MS)

    def _change_title(self, title):
        if title == self._music_title:
            return
        self._old_title = self._music_title
        self._music_title = title
        self._slide = 0.0

    def _poll_music(self):
        if self._mode == "panel":
            self._refresh_panel()
        title = None
        info = None
        if self._media_getter is not None:
            try:
                info = self._media_getter()
            except Exception:
                info = None
        if info and info.get("title"):
            self._media, self._media_t = info, time.time()
            title = (info["title"] + " - " + info["artist"]) if info.get("artist") else info["title"]
            playing = bool(info.get("playing"))
        elif self._music_getter is not None:
            try:
                title = self._music_getter()
            except Exception:
                title = None
            self._media = None
            playing = bool(title)
        else:
            return
        self._music_on = playing
        if not playing:
            title = None      # duraklatilmis / bos: "yeni sarki" penceresi acilmasin
        if title and title != self._last_music:
            self._last_music = title
            if self._mode == "music":
                self._change_title(title)
                if not self.underMouse():
                    self._hold.start(MUSIC_SHOW_MS)
            elif self._mode in ("idle", "voice"):
                self._music_title = title
                self._slide = 1.0
                self._set_mode("music")
                self._hold.start(MUSIC_SHOW_MS)
        elif not title:
            self._last_music = None

    def _on_tick(self):
        self._phase += 0.12
        if self._slide < 1.0:
            self._slide = min(1.0, self._slide + 0.07)
        v = self._level
        self._level *= 0.5
        self._levels.append(v)
        now = time.time()
        if v > VOICE_THRESHOLD:
            self._last_voice = now
            if self._mode in ("idle", "music", "mascot"):
                self._hold.stop()
                self._set_mode("voice")
        elif self._mode == "voice" and now - self._last_voice > VOICE_HOLD:
            self._set_mode("idle")
        self._update_follow(now)
        if self._mode == "lyrics" and now - self._lyr_check > 0.25:
            self._lyr_check = now
            self._refresh_lyrics()
        self.update()

    def _update_follow(self, now):
        """Gozler fareyi izler. Fare 8 sn kipirdamazsa gozler yine serbestce etrafa bakar."""
        try:
            pos = QCursor.pos()
            if self._last_cursor is None or pos != self._last_cursor:
                self._last_cursor = pos
                self._cursor_moved = now
            if now - self._cursor_moved > 8.0:
                self._follow = None
            else:
                c = self.mapToGlobal(self.rect().center())
                if self._mode == "mascot":      # fare adanin uzerinde: ada boyuna gore
                    dx = (pos.x() - c.x()) / max(60.0, self.width() / 2.0)
                    dy = (pos.y() - c.y()) / max(30.0, self.height() / 2.0)
                else:                           # ekranin her yerinden izle
                    dx = (pos.x() - c.x()) / 500.0
                    dy = (pos.y() - c.y()) / 350.0
                self._follow = (max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy)))
            m = self._mascot
            if m is not None:
                if self._follow is None:
                    m.set_follow(None, None)
                else:
                    m.set_follow(self._follow[0] * 3.0, self._follow[1] * 1.5)
        except Exception:
            self._follow = None

    def _on_hud_level(self, level):
        try:
            import jarvis_hud
            jarvis_hud.set_level(level)
        except Exception as e:
            print("HUD hata:", e)

    def _on_hud_hide(self):
        try:
            import jarvis_hud
            jarvis_hud.hide()
        except Exception:
            pass

    def _on_react(self, name, label):
        """El hareketine maskot tepkisi: sarki degisince dans, ekran goruntusunde flas."""
        m = self._mascot
        # sadece ekran goruntusunde maskot flas yapar; diger hareketlerde eskisi gibi kisa yazi cikar
        if name != "screenshot" or m is None or self._speaking or self._mode in ("panel", "lyrics", "voice"):
            if label:
                self._on_text("gesture", label)
            return
        self._react_id += 1
        rid = self._react_id
        m.set_label(label)
        if self._mode != "mascot":
            self._set_mode("mascot")
        m.flash()
        self._hold.start(2400)
        QTimer.singleShot(2500, lambda: m.set_label("") if rid == self._react_id else None)

    # ── cizim ──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(r.height() / 2.0, 22.0)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QBrush(BODY))
        p.setPen(QPen(QColor(0, 180, 255, 90), 1))
        p.drawPath(path)
        p.setClipPath(path)

        if self._mode == "idle":
            self._paint_idle(p, r)
        elif self._mode == "voice":
            self._paint_voice(p, r)
        elif self._mode == "music":
            self._paint_music(p, r)
        elif self._mode == "text":
            self._paint_text(p, r)
        elif self._mode == "mascot":
            self._paint_mascot_buttons(p)
        elif self._mode == "lyrics":
            self._paint_lyrics(p, r)
        elif self._mode == "panel":
            self._paint_panel(p, r)

    def _pulse(self):
        import math
        return 0.5 + 0.5 * math.sin(self._phase)

    def _paint_idle(self, p, r):
        now = time.time()
        dt = min(0.1, now - self._eye_last) if self._eye_last else 0.033
        self._eye_last = now

        # goz kirpma
        blink = 1.0
        if self._eye_blink is None and now >= self._eye_next_blink:
            self._eye_blink = now
        if self._eye_blink is not None:
            u = (now - self._eye_blink) / 0.16
            if u >= 1.0:
                self._eye_blink = None
                self._eye_next_blink = now + random.uniform(2.5, 5.5)
            else:
                blink = max(0.1, 1.0 - math.sin(math.pi * u))

        # etrafa bakma
        if self._follow is not None:
            self._eye_target = (self._follow[0] * 4.5, self._follow[1] * 2.2)
            self._eye_next_look = now + 0.3
        elif now >= self._eye_next_look:
            if random.random() < 0.6:
                self._eye_target = (random.uniform(-3.5, 3.5), random.uniform(-1.2, 1.2))
            else:
                self._eye_target = (0.0, 0.0)
            self._eye_next_look = now + random.uniform(1.5, 4.0)
        k = 1.0 - math.exp(-dt * 6.0)
        self._eye_look = (self._eye_look[0] + (self._eye_target[0] - self._eye_look[0]) * k,
                          self._eye_look[1] + (self._eye_target[1] - self._eye_look[1]) * k)
        ox, oy = self._eye_look

        cx, cy = r.center().x(), r.center().y()
        ex = 9.0                                   # iki goz arasi yarim mesafe
        if self._music_on:
            # muzik calarken mutlu gozler: ^ ^  (hafifce sallanir)
            bob = 1.0 * math.sin(self._phase * 0.9)
            pen = QPen(AMBER, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for sign in (-1, 1):
                rc = QRectF(cx + sign * ex + ox - 4.5, cy - 2.5 + bob + oy, 9.0, 8.0)
                path = QPainterPath()
                path.arcMoveTo(rc, 20)
                path.arcTo(rc, 20, 140)
                p.drawPath(path)
        else:
            rx, ry = 2.7, 4.6 * blink
            p.setPen(Qt.NoPen)
            for sign in (-1, 1):
                pos = QPointF(cx + sign * ex + ox, cy + oy)
                p.setBrush(QColor(CYAN.red(), CYAN.green(), CYAN.blue(), 38))   # yumusak parilti
                p.drawEllipse(pos, rx + 2.2, ry + 2.2)
                a = int(215 + 40 * self._pulse())
                p.setBrush(QColor(CYAN.red(), CYAN.green(), CYAN.blue(), a))
                p.drawEllipse(pos, rx, ry)
        if self._gesture_on:
            # el modu acik (kamera calisiyor): sagda kucuk halka + nokta
            a = int(150 + 100 * self._pulse())
            gp = QPointF(cx + 38.0, cy)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(CYAN.red(), CYAN.green(), CYAN.blue(), a), 1.4))
            p.drawEllipse(gp, 4.2, 4.2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(CYAN.red(), CYAN.green(), CYAN.blue(), a))
            p.drawEllipse(gp, 1.6, 1.6)

    def _paint_voice(self, p, r):
        n = len(self._levels)
        bw, gap = 4.0, 3.0
        total = n * bw + (n - 1) * gap
        x = r.center().x() - total / 2.0
        mid = r.center().y()
        maxh = r.height() - 14
        p.setPen(Qt.NoPen)
        for l in self._levels:
            l = min(1.0, l * 1.6)
            h = 3 + l * maxh
            col = QColor(CYAN.red(), CYAN.green(), CYAN.blue(), int(110 + 140 * l))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, mid - h / 2.0, bw, h), 2, 2)
            x += bw + gap

    def _paint_music(self, p, r):
        import math
        p.setPen(AMBER)
        p.setFont(QFont("Segoe UI Symbol", 13))
        p.drawText(QRectF(r.left() + 16, r.top(), 24, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, "♪")
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        area = QRectF(r.left() + 44, r.top(), r.width() - 200, r.height())
        p.save()
        p.setClipRect(area, Qt.IntersectClip)
        t = 1.0 - (1.0 - self._slide) ** 3
        tw = int(area.width())
        if self._slide < 1.0 and self._old_title:
            p.setPen(QColor(235, 245, 255, int(255 * (1 - t))))
            p.drawText(QRectF(area.left() - 40 * t, area.top(), area.width(), area.height()),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(self._old_title, Qt.ElideRight, tw))
        p.setPen(QColor(235, 245, 255, int(255 * (t if self._old_title and self._slide < 1.0 else 1.0))))
        off = 40 * (1 - t) if self._slide < 1.0 else 0
        p.drawText(QRectF(area.left() + off, area.top(), area.width(), area.height()),
                   Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self._music_title, Qt.ElideRight, tw))
        p.restore()
        # kontrol dugmeleri: soz / onceki / oynat-durdur / sonraki
        lyr, prev, mid, nxt = self._btn_rects()
        self._draw_bubble(p, lyr, False)
        self._draw_transport(p, prev, mid, nxt)

    def _draw_bubble(self, p, rect, active):
        """Soz butonu: konusma balonu (icinde uc nokta)."""
        c = rect.center()
        p.setPen(Qt.NoPen)
        if active:
            p.setBrush(QColor(0, 180, 255, 38))
            p.drawEllipse(rect)
        p.setBrush(AMBER)
        p.drawRoundedRect(QRectF(c.x() - 8, c.y() - 7, 16, 12), 3.5, 3.5)
        tail = QPainterPath()
        tail.moveTo(c.x() - 4, c.y() + 4)
        tail.lineTo(c.x() - 5.5, c.y() + 8)
        tail.lineTo(c.x() + 1, c.y() + 4)
        p.drawPath(tail)
        p.setBrush(BODY)
        for dx in (-4.0, 0.0, 4.0):
            p.drawEllipse(QPointF(c.x() + dx, c.y() - 1), 1.3, 1.3)

    def _draw_transport(self, p, prev, mid, nxt):
        p.setPen(Qt.NoPen)
        p.setBrush(AMBER)
        c = prev.center()
        p.drawRect(QRectF(c.x() - 7, c.y() - 6, 2.5, 12))
        tri = QPainterPath()
        tri.moveTo(c.x() + 7, c.y() - 6); tri.lineTo(c.x() - 4, c.y()); tri.lineTo(c.x() + 7, c.y() + 6)
        p.drawPath(tri)
        c = mid.center()
        if self._music_on:
            # calarken: durdur (pause) simgesi
            p.drawRect(QRectF(c.x() - 5.5, c.y() - 6, 3.5, 12))
            p.drawRect(QRectF(c.x() + 2, c.y() - 6, 3.5, 12))
        else:
            # durunca: oynat (play) simgesi
            tri = QPainterPath()
            tri.moveTo(c.x() - 5, c.y() - 7); tri.lineTo(c.x() - 5, c.y() + 7); tri.lineTo(c.x() + 7, c.y())
            p.drawPath(tri)
        c = nxt.center()
        tri = QPainterPath()
        tri.moveTo(c.x() - 7, c.y() - 6); tri.lineTo(c.x() + 4, c.y()); tri.lineTo(c.x() - 7, c.y() + 6)
        p.drawPath(tri)
        p.drawRect(QRectF(c.x() + 4.5, c.y() - 6, 2.5, 12))

    def _paint_lyrics(self, p, r):
        W, H = float(r.width()), float(r.height())
        m = self._media or {}
        pos, dur = self._media_pos()
        lx = 18.0

        # nota karesi (kapak yerine)
        cover = QRectF(lx, 18.0, 54.0, 54.0)
        g = QLinearGradient(cover.topLeft(), cover.bottomRight())
        g.setColorAt(0.0, QColor(0, 70, 110))
        g.setColorAt(1.0, QColor(0, 28, 52))
        p.setPen(QPen(QColor(0, 180, 255, 90), 1))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(cover, 11, 11)
        p.setPen(AMBER)
        p.setFont(QFont("Segoe UI Symbol", 20))
        p.drawText(cover, Qt.AlignCenter, "♪")

        # baslik + sanatci
        tx = lx + 54.0 + 12.0
        tw = int(lx + LYR_LEFT_W - tx)
        tf = QFont("Segoe UI", 11)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor(240, 248, 255))
        title = m.get("title") or self._music_title or "Müzik"
        p.drawText(QRectF(tx, 20.0, tw, 22.0), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(tf).elidedText(title, Qt.ElideRight, tw))
        af = QFont("Segoe UI", 9)
        p.setFont(af)
        p.setPen(QColor(150, 170, 190))
        p.drawText(QRectF(tx, 44.0, tw, 18.0), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(af).elidedText(m.get("artist") or "", Qt.ElideRight, tw))

        # sure + ilerleme cubugu
        sf = QFont("Segoe UI", 8)
        p.setFont(sf)
        p.setPen(QColor(150, 170, 190))
        p.drawText(QRectF(lx, 79.0, 42.0, 18.0), Qt.AlignVCenter | Qt.AlignLeft, self._fmt_time(pos))
        p.drawText(QRectF(lx + LYR_LEFT_W - 50.0, 79.0, 50.0, 18.0), Qt.AlignVCenter | Qt.AlignRight,
                   ("-" + self._fmt_time(dur - pos)) if dur > 0 else "")
        bar = QRectF(lx + 46.0, 86.0, LYR_LEFT_W - 46.0 - 54.0, 4.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(bar, 2, 2)
        if dur > 0:
            fill = QRectF(bar.left(), bar.top(), bar.width() * min(1.0, pos / dur), bar.height())
            if fill.width() > 0.5:
                p.setBrush(AMBER)
                p.drawRoundedRect(fill, 2, 2)

        # dugmeler: soz (acik) / onceki / oynat-durdur / sonraki
        rects = self._lyr_btn_rects()
        self._draw_bubble(p, rects[0], True)
        self._draw_transport(p, rects[1], rects[2], rects[3])

        # ayirac cizgisi
        sepx = lx + LYR_LEFT_W + 14.0
        p.setPen(QPen(QColor(0, 180, 255, 50), 1))
        p.drawLine(QPointF(sepx, 22.0), QPointF(sepx, H - 22.0))

        # sag sutun: sozler
        ax = sepx + 16.0
        aw = W - ax - 18.0
        st, lines = self._lyr_state
        p.save()
        p.setClipRect(QRectF(ax - 4.0, 8.0, aw + 8.0, H - 16.0))
        if st != "ok" or not lines:
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(QColor(120, 150, 175))
            msg = "Sözler aranıyor…" if st == "loading" else "Bu şarkı için söz bulunamadı"
            p.drawText(QRectF(ax, 8.0, aw, H - 16.0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, msg)
        else:
            idx = _lyrics.index_at(lines, pos + LYRICS_LEAD)
            if idx != self._lyr_idx:
                self._lyr_idx = idx
                self._lyr_change = time.time()
            t = min(1.0, (time.time() - self._lyr_change) / 0.28)
            t = 1.0 - (1.0 - t) ** 3
            off = (1.0 - t) * 24.0           # yeni satir asagidan kayarak gelir

            def line_at(i):
                return (lines[i][1] or "♪") if 0 <= i < len(lines) else ""

            small = QFont("Segoe UI", 10)
            big = QFont("Segoe UI", 12)
            big.setBold(True)
            fm = QFontMetrics(small)
            p.setFont(small)
            p.setPen(QColor(150, 170, 190, int(70 * (1.0 - t))))
            p.drawText(QRectF(ax, -12.0 + off, aw, 26.0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(line_at(idx - 2), Qt.ElideRight, int(aw)))
            p.setPen(QColor(150, 170, 190, 130))
            p.drawText(QRectF(ax, 14.0 + off, aw, 26.0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(line_at(idx - 1), Qt.ElideRight, int(aw)))
            p.setFont(big)
            p.setPen(QColor(255, 255, 255, int(150 + 105 * t)))
            cur = line_at(idx) if idx >= 0 else "♪"
            p.drawText(QRectF(ax, 42.0 + off, aw, 62.0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, cur)
            p.setFont(small)
            p.setPen(QColor(150, 170, 190, 130))
            p.drawText(QRectF(ax, 108.0 + off, aw, 26.0), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(line_at(idx + 1), Qt.ElideRight, int(aw)))
        p.restore()

    def _glyph(self, p, kind, rect, color):
        cx, cy = rect.center().x(), rect.center().y()
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if kind == "tasks":
            p.drawRoundedRect(QRectF(cx - 6, cy - 6, 12, 12), 3, 3)
            path = QPainterPath()
            path.moveTo(cx - 3, cy)
            path.lineTo(cx - 1, cy + 3)
            path.lineTo(cx + 4, cy - 3)
            p.drawPath(path)
        elif kind == "notes":
            p.drawLine(QPointF(cx - 6, cy - 4), QPointF(cx + 6, cy - 4))
            p.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
            p.drawLine(QPointF(cx - 6, cy + 4), QPointF(cx + 1, cy + 4))
        elif kind == "phone":
            # telefon: dikdortgen govde + ust hoparlor cizgisi
            p.drawRoundedRect(QRectF(cx - 4.0, cy - 6.5, 8.0, 13.0), 2.0, 2.0)
            p.drawLine(QPointF(cx - 1.5, cy - 4.3), QPointF(cx + 1.5, cy - 4.3))
        elif kind == "hand":
            # el: avuc + dort parmak + basparmak
            p.drawRoundedRect(QRectF(cx - 4.5, cy - 1, 9, 7), 2.5, 2.5)
            for dx, top in ((-3.0, -6.0), (-1.0, -7.5), (1.0, -7.0), (3.0, -5.5)):
                p.drawLine(QPointF(cx + dx, cy - 1), QPointF(cx + dx, cy + top))
            p.drawLine(QPointF(cx - 4.5, cy + 2), QPointF(cx - 7, cy - 1))
        else:
            # pano: arkada bir sayfa, onde baska bir sayfa
            p.drawRoundedRect(QRectF(cx - 6, cy - 6, 9, 10), 2, 2)
            p.drawRoundedRect(QRectF(cx - 2, cy - 2, 9, 10), 2, 2)

    def _paint_mascot_buttons(self, p):
        rects = self._mascot_btn_rects()
        for kind, rect in (zip([k for k, _n, _w in _TABS], rects) if _panels is not None else ()):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 180, 255, 34))
            p.drawEllipse(rect)
            self._glyph(p, kind, rect, AMBER)
        n_tabs = len(_TABS)
        for off, key in enumerate(self._extra_btn_keys()):
            rect = rects[n_tabs + off]
            on = key == "hand" and self._gesture_on
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 180, 255, 150 if on else 34))
            p.drawEllipse(rect)
            self._glyph(p, key, rect, QColor(255, 255, 255) if on else AMBER)

    def _paint_panel(self, p, r):
        tabs = [(k, n) for k, n, _w in _TABS]
        tf = QFont("Segoe UI", 8)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(tf)
        for (key, name), rect in zip(tabs, self._tab_rects()):
            active = key == self._tab
            if active:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 180, 255, 40))
                p.drawRoundedRect(rect, 12, 12)
            n = self._counts.get(key, 0)
            p.setPen(AMBER if active else QColor(135, 165, 190))
            p.drawText(rect, Qt.AlignCenter, f"{name} {n}" if n else name)
        # kapat (x)
        c = self._close_rect().center()
        p.setPen(QPen(QColor(135, 165, 190), 1.6))
        p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))
        # ayirac
        p.setPen(QPen(QColor(0, 180, 255, 50), 1))
        p.drawLine(QPointF(r.left() + 14, r.top() + PANEL_HEAD - 4),
                   QPointF(r.right() - 14, r.top() + PANEL_HEAD - 4))

        if not self._rows:
            p.setFont(self._font)
            p.setPen(QColor(120, 150, 175))
            p.drawText(QRectF(r.left() + 18, r.top() + PANEL_HEAD, r.width() - 36, ROW_H),
                       Qt.AlignVCenter | Qt.AlignLeft, self._empty)
            return

        lead_font = QFont("Segoe UI", 9)
        done_font = QFont(self._font)
        done_font.setStrikeOut(True)
        for i, row in enumerate(self._rows):
            y = r.top() + PANEL_HEAD + i * ROW_H
            x = r.left() + 18
            done = row["done"]
            if self._tab == "tasks":
                p.setFont(lead_font)
                p.setPen(QColor(100, 130, 155))
                p.drawText(QRectF(x, y, 16, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, row["lead"])
                box = QRectF(x + 20, y + (ROW_H - 12) / 2.0, 12, 12)
                if done:
                    p.setPen(QPen(AMBER, 1.4))
                    p.setBrush(QColor(255, 190, 0, 45))
                else:
                    p.setPen(QPen(CYAN, 1.4))
                    p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(box, 3, 3)
                if done:
                    pen = QPen(AMBER, 1.8)
                    pen.setCapStyle(Qt.RoundCap)
                    p.setPen(pen)
                    p.drawLine(QPointF(box.left() + 3, box.center().y()),
                               QPointF(box.left() + 5.5, box.bottom() - 3))
                    p.drawLine(QPointF(box.left() + 5.5, box.bottom() - 3),
                               QPointF(box.right() - 2.5, box.top() + 3))
                tx = x + 44
            else:
                lead_w = 50 if self._tab == "notes" else (22 if self._tab == "clips" else 100)
                p.setFont(lead_font)
                if self._tab == "clips" and i == self._clip_flash_row and time.time() < self._clip_flash:
                    p.setPen(AMBER)
                    row = dict(row, text="Kopyalandı ✓")
                else:
                    p.setPen(QColor(120, 160, 190))
                p.drawText(QRectF(x, y, lead_w, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, row["lead"])
                tx = x + lead_w + 8
            font = done_font if done else self._font
            p.setFont(font)
            if done:
                p.setPen(QColor(105, 130, 150))
            elif row["dim"]:
                p.setPen(QColor(150, 170, 190))
            else:
                p.setPen(QColor(235, 245, 255))
            avail = int(r.right() - 16 - tx)
            p.drawText(QRectF(tx, y, avail, ROW_H), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(font).elidedText(row["text"], Qt.ElideRight, avail))
        if self._extra:
            p.setFont(lead_font)
            p.setPen(QColor(100, 130, 155))
            y = r.top() + PANEL_HEAD + len(self._rows) * ROW_H
            p.drawText(QRectF(r.left() + 18, y, r.width() - 36, 18),
                       Qt.AlignVCenter | Qt.AlignLeft, f"+{self._extra} daha")

    def _paint_text(self, p, r):
        cy = r.center().y()
        p.setPen(Qt.NoPen)
        left = self._text_left()
        if self._mascot_speaks():
            pass   # solda maskot var, nokta cizme
        elif self._kind == "phone":
            # kucuk telefon simgesi
            p.setPen(QPen(AMBER, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(r.left() + 17, cy - 8, 9, 16), 2.5, 2.5)
            p.drawLine(int(r.left() + 20), int(cy + 5), int(r.left() + 23), int(cy + 5))
        else:
            a = int(150 + 100 * self._pulse())
            p.setBrush(QColor(CYAN.red(), CYAN.green(), CYAN.blue(), a))
            p.drawEllipse(QRectF(r.left() + 18, cy - 4, 8, 8))
        p.setFont(self._font)
        p.setPen(QColor(235, 245, 255))
        p.drawText(QRectF(r.left() + left, r.top() + 4, r.width() - left - 18, r.height() - 8),
                   Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self._text)


def attach(music_getter=None, response_callbacks=None, effect_signals=None, media_getter=None,
           gesture_toggle=None, preview_cb=None, phone_cb=None):
    """jarvis_voice.py'nin _launch_main fonksiyonundan cagrilir.
    Adayi olusturur ve JARVIS'in mevcut sinyallerine baglar."""
    global _gesture_toggle_cb, _preview_cb, _phone_cb
    _gesture_toggle_cb = gesture_toggle
    _preview_cb = preview_cb
    _phone_cb = phone_cb
    island = IslandWidget(music_getter=music_getter, media_getter=media_getter)
    if response_callbacks is not None:
        response_callbacks.append(lambda t: notify(t, "speak"))
    if effect_signals is not None:
        try:
            effect_signals.voice_level.connect(island.set_level)
        except Exception as e:
            print("Island: mikrofon seviyesine baglanamadi:", e)
    return island