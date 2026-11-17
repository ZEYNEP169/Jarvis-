# -*- coding: utf-8 -*-
"""
JARVIS HUD: holografik DUNYA HARITASI (Iron Man tarzi overlay)
================================================================
Elleri V isaretiyle birbirinden uzaklastirip yaklastirinca (jarvis_gesture.py: "world_in" / "world_out" /
"world_exit") ekranda noktalardan olusan holografik bir dunya haritasi buyur / kuculur:
gece-gunduz siniri, tarama cizgisi, sehir isaretleri, akan veri yaylari, koseli cerceve ve UTC saati.

Kullanim (jarvis_voice.py icinden, jarvis_island.py uzerinden) - ESKISIYLE AYNI, o dosyalara dokunmak gerekmez:
    jarvis_island.hud_set_level(0.6)   # 0.0 (gorunmez) - 1.0 (tam buyuk) arasi
    jarvis_island.hud_close()          # yumusakca kapat

Pencere: cercevesiz, her zaman ustte, FARE TIKLAMALARINI GECIRIR (altindaki pencereyle calismaya devam edersin).
Harita verisi: Natural Earth (kamu malina acik) 110m kara parcalari, 2 derecelik nokta izgarasina cevrilmis, dosyanin icinde gomulu
(internet gerekmez).
"""

import math
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    import numpy as np
except Exception:                 # numpy yoksa kure yerine duz harita kullanilir
    np = None

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QLinearGradient, QPolygonF, QRadialGradient
from PyQt5.QtWidgets import QWidget, QApplication

# ── Ayarlar ──
SCREEN_FRAC = 0.96              # HUD ekranin en fazla ne kadarini kaplasin (genislik/yukseklik orani). 1.0 = tam ekran, 0.6 = kucuk
BASE_W = 1040                   # cizim bu "sanal" boyutta yapilir, pencere ekrana gore buyutulur
BASE_H = 600
W_FULL = BASE_W                 # gercek pencere boyu (asagida ekrana gore hesaplanir)
H_FULL = BASE_H
MIN_SCALE = 0.45                # level kucukken pencerenin en kucuk boyu (tam boyun orani)
DOT_SIZE = 3.8                  # kara noktalarinin capi (sanal piksel; buyuk = daha belirgin)
SCAN_SECONDS = 7.0              # tarama cizgisinin haritayi bir kez gecme suresi
HOME = "ISTANBUL"               # vurgulanan sehir (asagidaki listeden); ay yaylari buradan cikar
LIVE_DATA = True                # sehirlerde yerel saat + hava durumu (Open-Meteo, ucretsiz, API anahtari YOK). Internet yoksa sadece saat gorunur
LIVE_REFRESH = 600              # hava durumu kac saniyede bir yenilensin
MODE = "globe"                  # "globe" = donen 3B hologram kure, "map" = duz dunya haritasi
GLOBE_SPEED = 9.0               # kurenin donus hizi (derece/sn)
GLOBE_TILT = 18.0               # kurenin one egikligi (derece)
GLOBE_R = 225.0                 # kure yaricapi (sanal piksel)
GLOBE_SEE_THROUGH = True        # kurenin arka tarafi silik gorunsun (hologram hissi)
GLOBE_DOT = 3.4                 # kure noktalarinin capi
NIGHT_SHADE = True              # gece tarafi noktalari sonuk olsun mu

CYAN = QColor(70, 220, 255)
CYAN_LIGHT = QColor(200, 245, 255)
AMBER = QColor(255, 190, 70)

# Sehirler: (ad, enlem, boylam)
CITIES = [
    ("ISTANBUL", 41.01, 28.98), ("PARIS", 48.86, 2.35), ("NEW YORK", 40.71, -74.0),
    ("LOS ANGELES", 34.05, -118.24), ("SAO PAULO", -23.55, -46.63), ("LONDON", 51.51, -0.13),
    ("CAPE TOWN", -33.92, 18.42), ("DUBAI", 25.2, 55.27), ("MOSKOVA", 55.75, 37.62),
    ("TOKYO", 35.68, 139.69), ("SYDNEY", -33.87, 151.21), ("SINGAPUR", 1.35, 103.82),
]
ARCS_TO = ["NEW YORK", "TOKYO", "SYDNEY", "SAO PAULO", "DUBAI", "CAPE TOWN", "LOS ANGELES", "MOSKOVA"]

# Harita izgarasi: 2 derece adim, enlem 84 (kuzey) .. -60 (guney), boylam -180 .. 180. Her satir 180 bitlik hex.
_STEP = 2
_LAT_TOP, _LAT_BOT = 84, -60
_ROWS = [
    "0000000000007fc01ffc0000000000000000000000000",
    "00000000003fffffffffe0000000000000e0000000000",
    "00000000035fffffffff8000fc000000007c000000000",
    "000000070033e1ffffff000060000010000fc00000000",
    "00000000f8bfc007ffff00000000038007ffe001c0000",
    "0000001fcdf7f003fffe000000000c043fffffc0c0000",
    "003c0009fc37fe03fffe000003800c1dffffffffffc00",
    "01fffffffefd8f01fffc00003ff800fffffffffffffff",
    "f0ffffffffff87e1ff8000007ffefffffffffffffffff",
    "33ffffffffff9fc0fc03e001fbf7fffffffffffffffff",
    "00fffffffff883c0f8000007f7fffffffffffffffffff",
    "01ffffffffe01e003800000fe7ffffffffffffffff3f0",
    "00780fffffe01f4000000007e3fffffffffffffff2300",
    "003401fffffc1fe000000182c7ffffffffffffff00f00",
    "000000ffffffbff8000003c38ffffffffffffffc00e00",
    "0000007fffffbffc000006efffffffffffffffffc0c00",
    "0000003ffffffffc000001ffffffffffffffffffc0000",
    "0000001fffffffc6000000ffffffffffffffffff40000",
    "0000000fffffffc30000007fffffffffffffffff40000",
    "0000000fffffffe00000007fff97cffffffffffe40000",
    "0000000ffffffe00000007f9bf03cffffffffff8e0000",
    "0000000ffffffc00000007e2ffffe7ffffffffe080000",
    "0000000ffffff800000007c02dffe7fffffff8c080000",
    "00000007fffff0000000039e44fffffffffffe6380000",
    "00000007fffff000000001fe000ffffffffffc6f00000",
    "00000001ffffc000000007ff801ffffffffffe1800000",
    "00000000ffffc000000007ffeffffffffffffe0000000",
    "00000000ffe0c00000000fffffffdffffffffe0000000",
    "000000005fc0400000001fffffefeffffffffc0000000",
    "000000002f80000000003ffffffff4fffffffc0000000",
    "000000000780400000003ffffff7ff0ffffff20000000",
    "0000000007c6100000007ffffffbff07fcff400000000",
    "0000000003cc060000003ffffffbfe03f87e800000000",
    "0000000001fc000000003ffffffdfc03e07f020000000",
    "00000000001f000000007ffffffdf001c01f820000000",
    "000000000003000000007fffffff8001c01f810000000",
    "0000000000010f0000003fffffff7000c017018000000",
    "000000000000fff000001fffffffe000e010018000000",
    "0000000000001ff800000fffffffe0002008008000000",
    "0000000000001fff000007c7ffffc000002c180000000",
    "0000000000001fff80000001ffff8000003c380000000",
    "0000000000003fff80000001ffff0000001cfa0000000",
    "0000000000003fffe0000003fffe0000000c7a0800000",
    "0000000000003ffffc000001fffc00000006760f80000",
    "0000000000007fffff000000fffc000000020003e4000",
    "0000000000003fffff800000fffc00000001c001f0000",
    "0000000000003fffff800000fffc000000000080d8000",
    "0000000000001fffff0000007ffc00000000000000000",
    "0000000000001ffffe000000fffc20000000001c40000",
    "0000000000000ffffe000000fffc6000000000fc60000",
    "00000000000003fffe000000fffce000000001ffe0000",
    "00000000000001fffc000000fff0e000000001fff0000",
    "00000000000001fffc0000007ff0c00000000ffff8080",
    "00000000000001fff80000007ff0c00000001ffffc000",
    "00000000000001ffc00000007fe0800000001ffffc000",
    "00000000000003ffc00000007fe0000000001ffffe000",
    "00000000000003ffc00000003fc0000000001ffffe000",
    "00000000000003ff800000001f80000000000ffffe000",
    "00000000000003ff000000001f00000000000f87fc000",
    "00000000000003fe000000000000000000000801fc000",
    "00000000000007fc000000000000000000000000f8004",
    "00000000000007f000000000000000000000000000006",
    "00000000000007e00000000000000000000000001000c",
    "00000000000007c000000000000000000000000010018",
    "000000000000078000000000000000000000000000070",
    "0000000000000f8000000000000000000000000000000",
    "0000000000000f8000000000000000000000000000000",
    "0000000000000f0000000000000000000000000000000",
    "000000000000070000000000000000000000000000000",
    "000000000000038000000000000000000000000000000",
    "000000000000000000000000000000000000000000000",
    "000000000000000000000000000000000000000000000"
]

_LAND = []            # (lat, lon) merkezleri
for _i, _r in enumerate(_ROWS):
    _bits = bin(int("1" + _r, 16))[3:]
    for _j, _b in enumerate(_bits):
        if _b == "1":
            _LAND.append((_LAT_TOP - _i * _STEP - _STEP / 2.0, -180 + _j * _STEP + _STEP / 2.0))

# ── 3B kure icin onceden hesaplanan diziler ──
_G = None
if np is not None:
    _lat = np.radians(np.array([c[0] for c in _LAND]))
    _lon = np.radians(np.array([c[1] for c in _LAND]))
    _G = {"cos": np.cos(_lat), "sin": np.sin(_lat), "lon": _lon}


def _gc_points(a, b, n=44):
    """Iki (enlem, boylam) arasi buyuk daire noktalari: (cos enlem, sin enlem, boylam, yukseklik carpani)."""
    la1, lo1, la2, lo2 = (math.radians(v) for v in (a[0], a[1], b[0], b[1]))
    v1 = np.array([math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1)])
    v2 = np.array([math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2)])
    om = math.acos(max(-1.0, min(1.0, float(np.dot(v1, v2)))))
    u = np.linspace(0.0, 1.0, n)
    if om < 1e-6:
        pts = np.tile(v1, (n, 1))
    else:
        pts = (np.sin((1 - u) * om)[:, None] * v1 + np.sin(u * om)[:, None] * v2) / math.sin(om)
    lat = np.arcsin(np.clip(pts[:, 2], -1, 1))
    lon = np.arctan2(pts[:, 1], pts[:, 0])
    return np.cos(lat), np.sin(lat), lon, 1.0 + 0.2 * np.sin(math.pi * u)


def _grid_lines():
    out = []
    for lo in range(-180, 180, 30):                       # boylam cizgileri
        la = np.radians(np.linspace(-90, 90, 31))
        out.append((np.cos(la), np.sin(la), np.full(31, math.radians(lo))))
    for lat in (-60, -30, 0, 30, 60):                     # enlem cizgileri
        lo = np.radians(np.linspace(-180, 180, 73))
        la = np.full(73, math.radians(lat))
        out.append((np.cos(la), np.sin(la), lo))
    return out


_instance = None


def _sun_point(now):
    """Gunes tam tepede olan nokta (enlem, boylam)."""
    doy = now.timetuple().tm_yday
    lat = 23.44 * math.sin(2 * math.pi * (doy - 81) / 365.0)
    hours = now.hour + now.minute / 60.0 + now.second / 3600.0
    lon = -(hours - 12.0) * 15.0
    return lat, ((lon + 180) % 360) - 180


def _is_day(lat, lon, sun_lat, sun_lon):
    la, lo = math.radians(lat), math.radians(lon)
    sl, so = math.radians(sun_lat), math.radians(sun_lon)
    return math.sin(la) * math.sin(sl) + math.cos(la) * math.cos(sl) * math.cos(lo - so) > -0.05


class HudWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)     # tiklamalar alttaki pencereye gecer
        global W_FULL, H_FULL
        sc0 = QApplication.primaryScreen().availableGeometry()
        k0 = min(sc0.width() * SCREEN_FRAC / BASE_W, sc0.height() * SCREEN_FRAC / BASE_H)
        W_FULL, H_FULL = int(BASE_W * k0), int(BASE_H * k0)
        self._k = k0                               # sanal boydan gercek boya olcek
        self.resize(W_FULL, H_FULL)
        self._level = 0.0          # hedef seviye (0..1)
        self._shown = 0.0          # yumusakca takip eden gorunurluk
        self._t0 = time.monotonic()
        self._day_cache_t = 0.0
        self._day = [True] * len(_LAND)
        self._city = {c[0]: (c[1], c[2]) for c in CITIES}
        self._wx = {}              # ad -> (sicaklik, hava kodu, UTC farki saniye)
        self._wx_t = 0.0
        self._wx_busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._place()

    def _place(self):
        sc = QApplication.primaryScreen().availableGeometry()
        self.move(sc.center().x() - W_FULL // 2, sc.center().y() - H_FULL // 2)

    def set_level(self, lvl):
        self._level = max(0.0, min(1.0, lvl))
        if self._level > 0.0 and not self.isVisible():
            self._place()
            self.show()

    def hide_smooth(self):
        self._level = 0.0

    def _tick(self):
        self._shown += (self._level - self._shown) * 0.16
        if self._shown < 0.004 and self._level <= 0.0:
            if self.isVisible():
                self.hide()
            return
        self.update()

    # ── canli veri (arka planda, arayuzu dondurmaz) ──
    def _wx_fetch(self):
        try:
            import requests
            lats = ",".join(str(c[1]) for c in CITIES)
            lons = ",".join(str(c[2]) for c in CITIES)
            r = requests.get("https://api.open-meteo.com/v1/forecast",
                             params={"latitude": lats, "longitude": lons,
                                     "current": "temperature_2m,weather_code", "timezone": "auto"},
                             timeout=8)
            data = r.json()
            if isinstance(data, dict):
                data = [data]
            out = {}
            for c, d in zip(CITIES, data):
                cur = d.get("current") or {}
                out[c[0]] = (cur.get("temperature_2m"), cur.get("weather_code"), d.get("utc_offset_seconds"))
            if out:
                self._wx = out
        except Exception as e:
            print("HUD canli veri alinamadi:", type(e).__name__)
        finally:
            self._wx_busy = False

    def _wx_maybe(self):
        if not LIVE_DATA or self._wx_busy:
            return
        if time.monotonic() - self._wx_t < (LIVE_REFRESH if self._wx else 60):
            return
        self._wx_t = time.monotonic()
        self._wx_busy = True
        threading.Thread(target=self._wx_fetch, daemon=True).start()

    @staticmethod
    def _wx_text(code):
        if code is None:
            return ""
        if code == 0:
            return "açık"
        if code in (1, 2):
            return "az bulutlu"
        if code == 3:
            return "bulutlu"
        if code in (45, 48):
            return "sisli"
        if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            return "yağmurlu"
        if code in (71, 73, 75, 77, 85, 86):
            return "karlı"
        if code in (95, 96, 99):
            return "fırtına"
        return ""

    # ── yardimcilar ──
    def _update_day(self):
        now_m = time.monotonic()
        if now_m - self._day_cache_t < 30.0:
            return
        self._day_cache_t = now_m
        sl, so = _sun_point(datetime.now(timezone.utc))
        self._sun = (sl, so)
        self._day = [_is_day(la, lo, sl, so) for (la, lo) in _LAND]

    def paintEvent(self, _):
        if self._shown <= 0.004:
            return
        try:
            self._paint()
        except Exception as e:            # cizim hatasi uygulamayi dusurmesin
            print("HUD cizim hatasi:", e)

    def _paint(self):
        if MODE == "globe" and _G is not None:
            self._paint_globe()
        else:
            self._paint_map()

    def _gproj(self, coslat, sinlat, lonr, lam_c, cx, cy, R, lift=1.0):
        """Enlem/boylam -> ekran (x, y) ve derinlik z (z>0: kurenin on yuzu)."""
        ca, sa = self._g_ca, self._g_sa
        dl = lonr - lam_c
        x = coslat * np.sin(dl)
        z = coslat * np.cos(dl)
        y2 = sinlat * ca - z * sa
        z2 = sinlat * sa + z * ca
        return cx + R * lift * x, cy - R * lift * y2, z2

    def _paint_globe(self):
        s = self._shown
        t = time.monotonic() - self._t0
        self._update_day()
        self._wx_maybe()
        if not hasattr(self, "_g_grid"):
            self._g_grid = _grid_lines()
            self._g_arcs = []
            hl = self._city[HOME]
            for name in ARCS_TO:
                if name in self._city:
                    self._g_arcs.append(_gc_points(hl, self._city[name]))
            self._g_city = {c[0]: (math.cos(math.radians(c[1])), math.sin(math.radians(c[1])), math.radians(c[2]))
                            for c in CITIES}
        if getattr(self, "_g_day_t", None) != self._day_cache_t:
            self._g_day_t = self._day_cache_t
            self._g_day = np.array(self._day, dtype=bool)
        tilt = math.radians(GLOBE_TILT)
        self._g_ca, self._g_sa = math.cos(tilt), math.sin(tilt)
        lam_c = math.radians(self._city[HOME][1]) + math.radians(GLOBE_SPEED) * t       # HOME'dan baslayip doner

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        def col(c, a):
            return QColor(c.red(), c.green(), c.blue(), max(0, min(255, int(a * s))))

        sc = MIN_SCALE + (1.0 - MIN_SCALE) * s
        k = getattr(self, "_k", 1.0)
        p.translate(W_FULL / 2.0, H_FULL / 2.0)
        p.scale(sc * k, sc * k)
        p.translate(-BASE_W / 2.0, -BASE_H / 2.0)

        # ── panel + koseli cerceve + baslik ──
        panel = QRectF(12, 12, BASE_W - 24, BASE_H - 24)
        bg = QLinearGradient(0, 12, 0, 12 + BASE_H - 24)
        bg.setColorAt(0.0, QColor(4, 18, 30, int(185 * s)))
        bg.setColorAt(1.0, QColor(2, 10, 20, int(205 * s)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(panel, 14, 14)
        p.setPen(QPen(col(CYAN, 70), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(panel, 14, 14)
        L = 34
        p.setPen(QPen(col(CYAN, 230), 2.6))
        x0, y0, x1, y1 = panel.left() + 6, panel.top() + 6, panel.right() - 6, panel.bottom() - 6
        for (cx_, cy_, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(QPointF(cx_, cy_), QPointF(cx_ + dx * L, cy_))
            p.drawLine(QPointF(cx_, cy_), QPointF(cx_, cy_ + dy * L))
        f = QFont("Segoe UI", 12)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        p.setFont(f)
        p.setPen(col(CYAN_LIGHT, 240))
        p.drawText(QRectF(34, 24, 520, 26), Qt.AlignLeft | Qt.AlignVCenter, "J.A.R.V.I.S  //  KÜRESEL AĞ")
        f2 = QFont("Consolas", 10)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f2)
        now = datetime.now(timezone.utc)
        p.setPen(col(CYAN, 210))
        p.drawText(QRectF(BASE_W - 420, 24, 386, 26), Qt.AlignRight | Qt.AlignVCenter,
                   "UTC  " + now.strftime("%H:%M:%S") + "   ·   " + now.strftime("%d.%m.%Y"))
        pulse = 0.5 + 0.5 * math.sin(t * 4.0)
        p.setPen(Qt.NoPen)
        p.setBrush(col(AMBER, 120 + 135 * pulse))
        p.drawEllipse(QPointF(BASE_W - 440, 37), 4.5, 4.5)

        # ── kure ──
        cx, cy, R = BASE_W / 2.0, BASE_H / 2.0 + 14, GLOBE_R
        glow = QRadialGradient(QPointF(cx, cy), R * 1.4)
        glow.setColorAt(0.0, col(CYAN, 34))
        glow.setColorAt(0.72, col(CYAN, 26))
        glow.setColorAt(1.0, col(CYAN, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), R * 1.4, R * 1.4)
        body = QRadialGradient(QPointF(cx - R * 0.25, cy - R * 0.3), R * 1.15)
        body.setColorAt(0.0, col(QColor(40, 120, 170), 70))
        body.setColorAt(1.0, col(QColor(5, 30, 55), 120))
        p.setBrush(QBrush(body))
        p.setPen(QPen(col(CYAN, 190), 2.0))
        p.drawEllipse(QPointF(cx, cy), R, R)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col(CYAN, 55), 1.2))
        p.drawEllipse(QPointF(cx, cy), R * 1.07, R * 1.07)
        # olcek cizgileri (en dis halka)
        p.setPen(QPen(col(CYAN, 110), 1.4))
        for deg in range(0, 360, 5):
            rad = math.radians(deg + t * 6)
            r2 = R * (1.12 if deg % 30 == 0 else 1.095)
            p.drawLine(QPointF(cx + R * 1.07 * math.cos(rad), cy + R * 1.07 * math.sin(rad)),
                       QPointF(cx + r2 * math.cos(rad), cy + r2 * math.sin(rad)))

        # enlem / boylam izgarasi (on yuz)
        p.setPen(QPen(col(CYAN, 42), 1.0))
        for (cl, sl, lo) in self._g_grid:
            gx, gy, gz = self._gproj(cl, sl, lo, lam_c, cx, cy, R)
            path = QPainterPath()
            prev = False
            for xx, yy, zz in zip(gx.tolist(), gy.tolist(), gz.tolist()):
                if zz > 0:
                    if prev:
                        path.lineTo(QPointF(xx, yy))
                    else:
                        path.moveTo(QPointF(xx, yy))
                    prev = True
                else:
                    prev = False
            p.drawPath(path)

        # kara noktalari
        gx, gy, gz = self._gproj(_G["cos"], _G["sin"], _G["lon"], lam_c, cx, cy, R)
        front = gz > 0
        pen_cache = {}

        def dot_pen(a, light=False):
            key = (int(a) // 24, light)
            pn = pen_cache.get(key)
            if pn is None:
                pn = QPen(col(CYAN_LIGHT if light else CYAN, a), GLOBE_DOT)
                pn.setCapStyle(Qt.RoundCap)
                pen_cache[key] = pn
            return pn

        if GLOBE_SEE_THROUGH:                                  # arka taraf: cok silik
            m = ~front
            if m.any():
                p.setPen(dot_pen(34))
                p.drawPoints(QPolygonF([QPointF(a_, b_) for a_, b_ in zip(gx[m].tolist(), gy[m].tolist())]))
        scan_x = cx - R + ((t / 5.0) % 1.0) * 2 * R           # sola-saga giden tarama bandi
        boost = np.clip(1.0 - np.abs(gx - scan_x) / 38.0, 0.0, 1.0)
        day = self._g_day if NIGHT_SHADE else np.ones(len(gx), dtype=bool)
        alpha = np.where(day, 135 + 120 * gz, 45 + 60 * gz) + boost * 90
        alpha = np.clip(alpha, 0, 255)
        bins = (alpha // 24).astype(int)
        for light in (False, True):
            lm = front & ((boost > 0.35) == light)
            for b in np.unique(bins[lm]):
                mm = lm & (bins == b)
                p.setPen(dot_pen(float(b) * 24 + 12, light))
                p.drawPoints(QPolygonF([QPointF(a_, b_) for a_, b_ in zip(gx[mm].tolist(), gy[mm].tolist())]))
        # tarama bandinin parlak cizgisi (kurenin icinde)
        half = math.sqrt(max(0.0, R * R - (scan_x - cx) ** 2))
        p.setPen(QPen(col(CYAN_LIGHT, 90), 1.4))
        p.drawLine(QPointF(scan_x, cy - half), QPointF(scan_x, cy + half))

        # ── yorunge halkalari + uydu ──
        for (rot, rx, ry, sp, ph) in ((-22, 1.34, 0.30, 0.9, 0.0), (28, 1.26, 0.22, -0.6, 2.0)):
            p.save()
            p.translate(cx, cy)
            p.rotate(rot)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col(CYAN, 70), 1.2, Qt.DashLine))
            p.drawEllipse(QPointF(0, 0), R * rx, R * ry)
            ang = t * sp + ph
            p.setPen(Qt.NoPen)
            p.setBrush(col(CYAN_LIGHT, 240))
            p.drawEllipse(QPointF(R * rx * math.cos(ang), R * ry * math.sin(ang)), 3.8, 3.8)
            p.restore()

        # ── veri yaylari (HOME -> diger sehirler) ──
        for i, (cl, sl, lo, lift) in enumerate(self._g_arcs):
            ax, ay, az = self._gproj(cl, sl, lo, lam_c, cx, cy, R, lift)
            xs, ys, zs = ax.tolist(), ay.tolist(), az.tolist()
            path = QPainterPath()
            prev = False
            for xx, yy, zz in zip(xs, ys, zs):
                if zz > 0.02:
                    if prev:
                        path.lineTo(QPointF(xx, yy))
                    else:
                        path.moveTo(QPointF(xx, yy))
                    prev = True
                else:
                    prev = False
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col(CYAN, 105), 1.5))
            p.drawPath(path)
            n = len(xs)
            u = ((t * 0.3) + i * 0.17) % 1.0
            for kk in range(6):
                idx = int(max(0.0, u - kk * 0.02) * (n - 1))
                if zs[idx] > 0.02:
                    p.setPen(Qt.NoPen)
                    p.setBrush(col(CYAN_LIGHT, 240 - kk * 38))
                    p.drawEllipse(QPointF(xs[idx], ys[idx]), 2.8 - kk * 0.3, 2.8 - kk * 0.3)

        # ── sehirler ──
        lf = QFont("Consolas", 8)
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(lf)
        visible = []
        for (name, la, lo) in CITIES:
            cl, sl, lr = self._g_city[name]
            px, py, pz = self._gproj(np.array([cl]), np.array([sl]), np.array([lr]), lam_c, cx, cy, R)
            x, y, z = float(px[0]), float(py[0]), float(pz[0])
            if z <= 0.06:
                continue
            visible.append(name)
            is_home = (name == HOME)
            c = AMBER if is_home else CYAN_LIGHT
            fade = min(1.0, z * 2.2)
            ph_ = (t * (0.9 if is_home else 0.5) + (hash(name) % 100) / 100.0) % 1.0
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col(c, 190 * (1 - ph_) * fade), 1.4))
            rr = (5 if is_home else 3.5) + ph_ * (15 if is_home else 10)
            p.drawEllipse(QPointF(x, y), rr, rr)
            p.setPen(Qt.NoPen)
            p.setBrush(col(c, 250 * fade))
            p.drawEllipse(QPointF(x, y), 3.6 if is_home else 2.8, 3.6 if is_home else 2.8)
            right = x >= cx
            al = (Qt.AlignLeft if right else Qt.AlignRight) | Qt.AlignVCenter
            rx = x + 9 if right else x - 169
            p.setPen(col(c, (235 if is_home else 190) * fade))
            p.drawText(QRectF(rx, y - 20, 160, 14), al, name)
            w_ = self._wx.get(name)
            if w_ and w_[2] is not None:
                loc = datetime.now(timezone.utc) + timedelta(seconds=w_[2])
                info = loc.strftime("%H:%M") + ("  %d°C" % round(w_[0]) if w_[0] is not None else "")
                p.setPen(col(c, 230 * fade))
                p.drawText(QRectF(rx, y - 8, 160, 14), al, info)

        # ── sol panel: sehir listesi (yerel saat, sicaklik) ──
        p.setFont(f2)
        p.setPen(col(CYAN, 200))
        p.drawText(QRectF(34, 70, 220, 18), Qt.AlignLeft | Qt.AlignVCenter, "MERKEZLER")
        p.setPen(QPen(col(CYAN, 90), 1.0))
        p.drawLine(QPointF(34, 90), QPointF(210, 90))
        lf2 = QFont("Consolas", 9)
        p.setFont(lf2)
        yy = 98
        for (name, la, lo) in CITIES:
            vis = name in visible
            c = AMBER if name == HOME else (CYAN_LIGHT if vis else CYAN)
            p.setPen(col(c, 235 if vis else 130))
            w_ = self._wx.get(name)
            txt = ""
            if w_ and w_[2] is not None:
                loc = datetime.now(timezone.utc) + timedelta(seconds=w_[2])
                txt = loc.strftime("%H:%M") + ("  %d°" % round(w_[0]) if w_[0] is not None else "")
            p.drawText(QRectF(34, yy, 110, 16), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.drawText(QRectF(120, yy, 92, 16), Qt.AlignRight | Qt.AlignVCenter, txt)
            yy += 19

        # ── sag panel: durum ──
        sl_, so_ = getattr(self, "_sun", (0.0, 0.0))
        clon = ((math.degrees(lam_c) + 180) % 360) - 180
        p.setFont(f2)
        p.setPen(col(CYAN, 200))
        p.drawText(QRectF(BASE_W - 250, 70, 216, 18), Qt.AlignRight | Qt.AlignVCenter, "DURUM")
        p.setPen(QPen(col(CYAN, 90), 1.0))
        p.drawLine(QPointF(BASE_W - 210, 90), QPointF(BASE_W - 34, 90))
        p.setFont(lf2)
        p.setPen(col(CYAN, 215))
        lines = ["MERKEZ BOYLAM  %+.1f°" % clon, "GÜNEŞ  %.1f° / %.1f°" % (sl_, so_),
                 "NOKTA  %d" % len(_LAND), "MERKEZ  %d" % len(CITIES), "GÖRÜNEN  %d" % len(visible),
                 "TARAMA  AKTİF"]
        for i, ln in enumerate(lines):
            p.drawText(QRectF(BASE_W - 250, 98 + i * 19, 216, 16), Qt.AlignRight | Qt.AlignVCenter, ln)
        p.end()

    def _paint_map(self):
        s = self._shown
        t = time.monotonic() - self._t0
        self._update_day()
        self._wx_maybe()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        def col(c, a):
            return QColor(c.red(), c.green(), c.blue(), max(0, min(255, int(a * s))))

        # kucukten buyuge acilma: merkezden olcekle
        sc = MIN_SCALE + (1.0 - MIN_SCALE) * s
        k = getattr(self, "_k", 1.0)
        p.translate(W_FULL / 2.0, H_FULL / 2.0)
        p.scale(sc * k, sc * k)
        p.translate(-BASE_W / 2.0, -BASE_H / 2.0)

        # ── panel ──
        pw, ph = BASE_W - 24, BASE_H - 24
        panel = QRectF(12, 12, pw, ph)
        bg = QLinearGradient(0, 12, 0, 12 + ph)
        bg.setColorAt(0.0, QColor(4, 18, 30, int(185 * s)))
        bg.setColorAt(1.0, QColor(2, 10, 20, int(205 * s)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(panel, 14, 14)
        p.setPen(QPen(col(CYAN, 70), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(panel, 14, 14)

        # koseli cerceve (Iron Man tarzi)
        L = 34
        p.setPen(QPen(col(CYAN, 230), 2.6))
        x0, y0, x1, y1 = panel.left() + 6, panel.top() + 6, panel.right() - 6, panel.bottom() - 6
        for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * L))

        # ── baslik / alt bilgi ──
        f = QFont("Segoe UI", 12)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        p.setFont(f)
        p.setPen(col(CYAN_LIGHT, 240))
        p.drawText(QRectF(34, 24, 520, 26), Qt.AlignLeft | Qt.AlignVCenter, "J.A.R.V.I.S  //  DÜNYA AĞI")
        f2 = QFont("Consolas", 10)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f2)
        now = datetime.now(timezone.utc)
        p.setPen(col(CYAN, 210))
        p.drawText(QRectF(BASE_W - 420, 24, 386, 26), Qt.AlignRight | Qt.AlignVCenter,
                   "UTC  " + now.strftime("%H:%M:%S") + "   ·   " + now.strftime("%d.%m.%Y"))
        # canli durum noktasi
        pulse = 0.5 + 0.5 * math.sin(t * 4.0)
        p.setPen(Qt.NoPen)
        p.setBrush(col(AMBER, 120 + 135 * pulse))
        p.drawEllipse(QPointF(BASE_W - 440, 37), 4.5, 4.5)

        # ── harita alani ──
        mx0, my0 = 48.0, 66.0
        mw, mh = BASE_W - 96.0, BASE_H - 66.0 - 54.0
        lat_span = float(_LAT_TOP - _LAT_BOT)

        def proj(lat, lon):
            return (mx0 + (lon + 180.0) / 360.0 * mw, my0 + (_LAT_TOP - lat) / lat_span * mh)

        # enlem / boylam cizgileri (cok silik)
        p.setPen(QPen(col(CYAN, 26), 1.0))
        for lon in range(-180, 181, 30):
            x, _y = proj(0, lon)
            p.drawLine(QPointF(x, my0), QPointF(x, my0 + mh))
        for lat in range(_LAT_BOT, _LAT_TOP + 1, 30):
            _x, y = proj(lat, 0)
            p.drawLine(QPointF(mx0, y), QPointF(mx0 + mw, y))
        # ekvator biraz daha belirgin
        p.setPen(QPen(col(CYAN, 55), 1.0, Qt.DashLine))
        _x, ye = proj(0, 0)
        p.drawLine(QPointF(mx0, ye), QPointF(mx0 + mw, ye))

        # ── kara noktalari (gece tarafi sonuk, tarama cizgisi yakininda parlar) ──
        scan_x = mx0 + ((t / SCAN_SECONDS) % 1.0) * mw
        dot = DOT_SIZE
        p.setBrush(Qt.NoBrush)
        pens = {}

        def pen_for(a, c=CYAN):
            k = (a // 8, c.rgb())
            pn = pens.get(k)
            if pn is None:
                pn = QPen(col(c, a), dot)
                pn.setCapStyle(Qt.RoundCap)
                pens[k] = pn
            return pn

        buckets = {}
        for (la, lo), day in zip(_LAND, self._day):
            x, y = proj(la, lo)
            base = 235 if (day or not NIGHT_SHADE) else 85
            dd = abs(x - scan_x)
            if dd < 46:
                base = min(255, base + (46 - dd) * 4.2)
                c = CYAN_LIGHT
            else:
                c = CYAN
            buckets.setdefault((int(base) // 8, c.rgb()), (base, c, []))[2].append(QPointF(x, y))
        for (_k, (a, c, pts)) in buckets.items():
            p.setPen(pen_for(int(a), c))
            p.drawPoints(QPolygonF(pts))

        # tarama cizgisi
        sg = QLinearGradient(scan_x - 60, 0, scan_x, 0)
        sg.setColorAt(0.0, col(CYAN, 0))
        sg.setColorAt(1.0, col(CYAN, 60))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(sg))
        p.drawRect(QRectF(scan_x - 60, my0, 60, mh))
        p.setPen(QPen(col(CYAN_LIGHT, 190), 1.6))
        p.drawLine(QPointF(scan_x, my0), QPointF(scan_x, my0 + mh))

        # ── akan veri yaylari (HOME -> diger sehirler) ──
        hx, hy = proj(*self._city[HOME])
        for i, name in enumerate(ARCS_TO):
            if name not in self._city:
                continue
            tx, ty = proj(*self._city[name])
            midx, midy = (hx + tx) / 2.0, min(hy, ty) - 0.22 * math.hypot(tx - hx, ty - hy) - 14
            path = QPainterPath(QPointF(hx, hy))
            path.quadTo(QPointF(midx, midy), QPointF(tx, ty))
            p.setPen(QPen(col(CYAN, 70), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            u = ((t * 0.28) + i * 0.17) % 1.0                   # yay uzerinde giden isik
            for k in range(7):
                uu = max(0.0, u - k * 0.012)
                pt = path.pointAtPercent(uu)
                p.setPen(Qt.NoPen)
                p.setBrush(col(CYAN_LIGHT, 230 - k * 32))
                p.drawEllipse(pt, 2.6 - k * 0.25, 2.6 - k * 0.25)

        # ── sehir isaretleri ──
        lf = QFont("Consolas", 8)
        lf.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(lf)
        for (name, la, lo) in CITIES:
            x, y = proj(la, lo)
            is_home = (name == HOME)
            c = AMBER if is_home else CYAN_LIGHT
            ph_ = (t * (0.9 if is_home else 0.5) + (hash(name) % 100) / 100.0) % 1.0
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col(c, 190 * (1 - ph_)), 1.4))
            rr = (6 if is_home else 4) + ph_ * (16 if is_home else 11)
            p.drawEllipse(QPointF(x, y), rr, rr)
            p.setPen(Qt.NoPen)
            p.setBrush(col(c, 250))
            p.drawEllipse(QPointF(x, y), 3.6 if is_home else 2.6, 3.6 if is_home else 2.6)
            p.setPen(col(c, 235 if is_home else 170))
            right = (x < mx0 + mw - 110)
            al = (Qt.AlignLeft if right else Qt.AlignRight) | Qt.AlignVCenter
            rx = x + 8 if right else x - 168
            p.drawText(QRectF(rx, y - 30, 160, 14), al, name)
            w_ = self._wx.get(name)
            if w_ and w_[2] is not None:
                loc = datetime.now(timezone.utc) + timedelta(seconds=w_[2])
                info = loc.strftime("%H:%M")
                if w_[0] is not None:
                    info += "  %d°C" % round(w_[0])
                wt = self._wx_text(w_[1])
                if wt:
                    info += "  " + wt
                p.setPen(col(c, 255 if is_home else 215))
                p.drawText(QRectF(rx, y - 17, 160, 14), al, info)

        # ── alt cubuk: koordinat olcegi + durum ──
        p.setPen(QPen(col(CYAN, 120), 1.0))
        by = my0 + mh + 10
        p.drawLine(QPointF(mx0, by), QPointF(mx0 + mw, by))
        sf = QFont("Consolas", 8)
        p.setFont(sf)
        p.setPen(col(CYAN, 170))
        for lon in range(-180, 181, 60):
            x, _y = proj(0, lon)
            p.drawLine(QPointF(x, by), QPointF(x, by + 5))
            lab = ("%d°%s" % (abs(lon), "D" if lon > 0 else ("B" if lon < 0 else ""))) if lon else "0°"
            p.drawText(QRectF(x - 25, by + 6, 50, 14), Qt.AlignHCenter | Qt.AlignTop, lab)
        sl, so = getattr(self, "_sun", (0.0, 0.0))
        p.setFont(f2)
        p.setPen(col(CYAN, 200))
        p.drawText(QRectF(34, BASE_H - 44, 520, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   "TARAMA AKTİF  ·  GÜNEŞ  %.1f°  %.1f°" % (sl, so))
        p.drawText(QRectF(BASE_W - 420, BASE_H - 44, 386, 20), Qt.AlignRight | Qt.AlignVCenter,
                   "%d NOKTA  ·  %d MERKEZ" % (len(_LAND), len(CITIES)))
        p.end()


def _ensure():
    global _instance
    if _instance is None:
        _instance = HudWindow()
    return _instance


def show():
    _ensure()


def set_level(lvl):
    _ensure().set_level(lvl)


def hide():
    inst = _instance
    if inst is not None:
        inst.hide_smooth()