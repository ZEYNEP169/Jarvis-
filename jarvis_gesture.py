# -*- coding: utf-8 -*-
"""
JARVIS EL HAREKETLERI
=====================
Bilgisayarin kamerasi elini gorur, hareketleri komuta cevirir:

    Yumruk (✊)                         -> sarkiyi DURDUR   ("pause")
    Acik avuc (🖐), ~0.5 sn sabit       -> sarkiyi OYNAT    ("play")
    Eli saga dogru kaydir               -> SONRAKI sarki    ("next")
    Eli sola dogru kaydir               -> ONCEKI sarki     ("prev")

    Basparmak yukari (👍), tutarken      -> SES ARTAR        ("vol_up")
    Basparmak asagi (👎), tutarken       -> SES AZALIR       ("vol_down")
    V isareti (✌️), ~0.5 sn              -> EKRAN GORUNTUSU  ("screenshot")
    Uc parmak (isaret+orta+yuzuk), ~0.5 sn -> "BU NE?" ekrani acikla ("describe")
    Zoom (👌 gibi ama diger parmaklar kapali): basparmak+isaret parmagini ACARSAN parlaklik artar,
      KAPATIRSAN azalir ("bright_up" / "bright_down")
    OK isareti (👌), ~0.5 sn              -> SESI KAPAT / AC ("mute")
    Iki el V ISARETI yap, birbirinden UZAKLASTIR / YAKINLASTIR -> HOLOGRAFIK HUD ("world_in" / "world_out")
    El sallama (👋, sağ-sol sağ-sol), ~1 sn -> JARVIS'İ UYANDIR ("wake")
    Iki YUMRUK birlikte, ~0.6 sn -> EKRANI KİLİTLE ("lock")
    Isaret parmagi saga/sola (👉 👈), ~0.5 sn -> SONRAKI / ONCEKI sarki (kaydirmaya alternatif)
    Iki el acik (🙌), ~0.5 sn            -> el kontrollerini DURAKLAT / DEVAM ("freeze" / "unfreeze")

(Kamera goruntusu ayna gibi cevrilir: "sag" senin sagin.)

Iki parca var:
  GestureEngine      Kameradan bagimsiz, saf mantik. 21 el noktasi gelir, olay (event) cikar.
                     Test edilebilir, ayarlari asagidaki sabitlerde.
  GestureController  Kamerayi acar, MediaPipe ile el noktalarini bulur, motoru besler.

Gizlilik: Goruntu hicbir yere gonderilmez, kaydedilmez; her sey bilgisayarinda islenir.

Tek basina test (JARVIS'i acmadan):   python jarvis_gesture.py
  -> kamera penceresi acilir, algilanan hareketler konsola yazilir. Cikis: q ya da Esc.

Kurulum (bir kez):   pip install mediapipe opencv-python
Model dosyasi (~8 MB) ilk calistirmada otomatik indirilir: C:\\Jarvis\\hand_landmarker.task
"""

import os
import math
import time
import threading
from collections import deque, Counter

# ══════════════════════════════════════════
#  AYARLAR (istedigin gibi oyna)
# ══════════════════════════════════════════
CAMERA_INDEX = 0           # birden fazla kameran varsa 1, 2 dene (ya da: python jarvis_gesture.py --cameras)
CAMERA_FILE = ("C:\\Jarvis\\camera_index.txt" if os.name == "nt"
               else os.path.expanduser("~/.jarvis/camera_index.txt"))   # --cameras ile secilen kamera buraya kaydedilir


def _camera_index():
    try:
        with open(CAMERA_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return CAMERA_INDEX
FPS = 12                   # saniyede kac kare islensin (dusuk = pil/islemci dostu)
HOLD_SEC = 0.5             # yumruk / acik avuc bu kadar sure SABIT tutulunca calisir
STILL_MAX = 0.06           # "sabit" sayilmak icin el en fazla bu kadar oynayabilir (kare boyuna gore)
SWIPE_WIN = 0.5            # kaydirma bu sure icinde yapilmali (sn)
SWIPE_DIST = 0.2           # kaydirma icin elin yatayda gitmesi gereken mesafe (kare genisligi orani)
SWIPE_MIN_SEC = 0.12       # bundan kisa surede olan (titreme) hareketler sayilmaz
SWIPE_SPEED = 0.6          # kaydirma en az bu hizda olmali (kare genisligi / sn). Yavas geri cekme sayilmaz
COOLDOWN = 0.4             # bir kaydirmadan sonra en az bu kadar bekle (sn)
REARM_STILL = 0.2          # kaydirmadan sonra el bu kadar sure durunca yeni hareket kabul edilir
EXT_RATIO = 1.2            # parmak ucu / eklem uzakliklari orani: bundan buyukse parmak ACIK
FOLD_RATIO = 1.0           # bundan kucukse parmak KAPALI
SMOOTH_FRAMES = 5          # el seklini bu kadar karenin cogunluguna gore belirle (titremeyi onler)
LOST_RESET = 0.8           # el bu kadar sure gorunmezse her sey sifirlanir
VOL_HOLD = 0.35            # basparmak yukari/asagi bu kadar sure tutulunca ses degisir
VOL_REPEAT = 0.45          # basparmak tutuldukca ses bu aralikla tekrar degisir (sn)
SHOT_COOLDOWN = 2.0        # iki ekran goruntusu arasi en az bekleme (sn)
TWO_HAND_SEP = 0.2         # iki elin avuc merkezleri en az bu kadar uzak olmali (MediaPipe bazen tek eli iki kez bulur)
TWO_HAND_HOLD = 1.0        # iki el acik bu kadar sure tutulunca duraklat/devam
THUMB_OUT = 0.7            # basparmak ucu / isaret parmagi kokune uzaklik (avuc boyuna gore): bundan buyukse parmak ACIK
POINT_REPEAT = 1.2         # isaret parmagi tutuldukca sarki bu aralikla tekrar degisir (sn)
NO_SWIPE = ("fist", "thumb_up", "thumb_down", "victory", "point_left", "point_right", "three", "ok", "zoom", "rock")
# bir sekil HOLD_SEC sure sabit tutulunca calisan olaylar ve her birinin yeniden calisma bekleme suresi (sn)
HOLD_EVENTS = {"open": "play", "fist": "pause", "victory": "screenshot", "three": "describe", "ok": "mute", "rock": "mouse_on"}
HOLD_COOLDOWN = {"victory": 2.0, "three": 6.0, "ok": 1.0, "rock": 1.5}   # bu seklin tutulurken kaydirma sayilmaz
PREVIEW_W, PREVIEW_H = 192, 144   # canli kamera penceresindeki goruntu boyutu (kucultmek icin azalt)
HAND_ONLY_PREVIEW = True   # True: onizlemede YUZUN/ODANIN goruntusu gizlenir, sadece el iskeleti gorunur (video cekerken). False: kamera goruntusu
LOCK_HOLD = 0.6            # iki yumruk bu kadar sure tutulunca ekran kilitlenir
LOCK_COOLDOWN = 3.0        # iki kilitleme arasi en az bekleme (sn)
WAVE_WIN = 1.3             # el sallama: bu sure icindeki yatay hareket incelenir
WAVE_MIN_REV = 3           # en az bu kadar yon degisikligi olmali (sag-sol-sag-sol...)
WAVE_COOLDOWN_G = 4.0      # iki "uyandirma" sallamasi arasi en az bekleme (sn)
WORLD_STEP = 0.045         # HUD acikken bu kadar mesafe degisince bir adim buyut/kucult
ZOOM_FOLD = 1.15           # zoom girisinde orta/yuzuk/serce parmak icin "kapali" sayilma siniri (daha hosgorulu)
BRIGHT_HOLD = 0.4          # IKI el da basparmak yukari/asagi bu kadar sure tutulunca parlaklik degisir
BRIGHT_REPEAT = 0.5        # iki el basparmak tutuldukca parlaklik bu aralikla degisir (sn)
ZOOM_ENABLED = False       # parlaklik hareketi (L sekli). False = tamamen kapali, yanlislikla tetiklenmez
ZOOM_HOLD = 0.35           # zoom (parlaklik) sekli bu kadar sure tutulunca ayar baslar
ZOOM_STEP = 0.07           # basparmak-isaret parmagi mesafesi (avuc boyuna gore) bu kadar degisince bir adim parlaklik
# ── Hava faresi (rock isareti ile ac/kapa; isaret parmagi = imlec, basparmak+isaret birlesince = tik) ──
MOUSE_BOX = (0.25, 0.75, 0.20, 0.65)  # kamerada elin gezecegi alan (x0, x1, y0, y1; 0..1). KUCUK alan = imlec HIZLI (az hareketle tum ekran)
MOUSE_FPS = 30             # fare modundayken saniyede kac kare islensin (yuksek = akici imlec, biraz daha islemci)
MOUSE_MINCUT = 1.0         # titreme filtresi: kucuk = el dururken imlec cok sabit (ama yavas hareketlerde biraz gecikir)
MOUSE_BETA = 15.0          # titreme filtresi: buyuk = hizli harekette gecikme yok (cok buyuk = titrer)
MOUSE_DEADZONE = 0.0015    # bundan kucuk kayma yok sayilir (imlec dururken titremesin)
MOUSE_DWELL = 0.0          # imleci bu kadar sn bir yerde tutunca TIK olur (0 = kapali; denemek icin 1.2 yap)
MOUSE_DWELL_RADIUS = 0.025 # "bir yerde tutmak" icin imlecin en fazla bu kadar oynamasi serbest (ekran orani)
MOUSE_FREEZE = 0.60        # basparmak-isaret mesafesi bunun altina inince imlec DONAR (tik sirasinda kaymasin)
MOUSE_PINCH_ON = 0.30      # bu kadar yaklasinca sol tik BASILIR
MOUSE_PINCH_OFF = 0.50     # bu kadar acilinca sol tik BIRAKILIR (surukleme icin basili tutabilirsin)
MOUSE_PINCH_FRAMES = 2     # tik icin pinch en az bu kadar kare surmeli
MOUSE_RCLICK = 0.30        # basparmak + ORTA parmak birlesirse sag tik
MOUSE_RCLICK_CD = 0.8      # iki sag tik arasi en az bekleme (sn)
MOUSE_PUSH_CLICK = True    # isaret parmagini kameraya DOGRU it / bukerek "bas" = sol tik (False: kapali)
MOUSE_PUSH_FREEZE = 0.88   # parmak boyu normalin bu oranina inince imlec DONAR (itme baslarken kaymasin)
MOUSE_PUSH_ON = 0.72       # parmak boyu normalin bu oranina inerse TIK olur (kucultunce tik daha kolay, buyutunce zor)
MOUSE_PUSH_OFF = 0.85      # parmak bu orana geri donunce yeni tik icin hazir
MOUSE_PUSH_CD = 0.5        # iki itme-tik arasi en az bekleme (sn)
MOUSE_CLICK_SECOND = True   # True: TIK = diger elini YUMRUK yapmak (yumruk tutarsan surukleme), V = sag tik. Imlec eli hicbir sekilde tiklamaz. False: eski yontem (basparmak-isaret / itme)
MOUSE_CLOSED_RATIO = 1.12  # tik elinde parmak "kapali" sayilma siniri (buyutursan yumruk daha kolay algilanir)
MOUSE_RCLICK_HOLD = 0.7    # sag tik icin V isaretini bu kadar sn tut (cok hizli algilamasin)
MOUSE_CLICK_FRAMES = 3     # tik icin yumrugun bu kadar kare ust uste gorunmesi gerekir (yanlis tiki onler)
MOUSE_OFF_TWO_HANDS = True # True: fare modu sadece IKI EL ROCK yapinca kapanir (yanlislikla kapanmaz). False: eski tek el yontemi
MOUSE_OFF_TWO = 1.0        # iki el rock bu kadar sn tutulunca fare modu kapanir
MOUSE_OFF_HOLD = 1.5       # (tek el yontemi) rock isaretini bu kadar SABIT tutarsan fare modu kapanir
MOUSE_LOST_OFF = 8.0       # el bu kadar sure gorunmezse fare modu kendiliginden kapanir (guvenlik)
DEBUG = False              # True: konsola her saniye el seklini yazar

DATA_DIR = r"C:\Jarvis" if os.name == "nt" else os.path.expanduser("~/.jarvis")
MODEL_PATH = os.path.join(DATA_DIR, "hand_landmarker.task")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

# MediaPipe el noktalari: 0=bilek, parmak ucu / orta eklem (PIP)
_TIPS = (8, 12, 16, 20)       # isaret, orta, yuzuk, serce
_PIPS = (6, 10, 14, 18)
_PALM = (0, 5, 9, 13, 17)     # avuc merkezi icin noktalar

LABELS = {"play": "Oynatılıyor", "pause": "Durduruldu",
          "next": "Sonraki şarkı", "prev": "Önceki şarkı",
          "vol_up": "Ses artıyor", "vol_down": "Ses azalıyor",
          "screenshot": "Ekran görüntüsü alındı",
          "bright_up": "Parlaklık artıyor", "bright_down": "Parlaklık azalıyor",
          "lock": "Ekran kilitlendi", "wake": "Merhaba!",
          "world_in": "Harita büyüyor", "world_out": "Harita küçülüyor", "world_exit": "Harita kapandı",
          "describe": "Ekrana bakılıyor", "mute": "Ses kapat / aç",
          "freeze": "El kontrolleri duraklatıldı", "unfreeze": "El kontrolleri devam ediyor",
          "mouse_on": "Hava faresi açık", "mouse_off": "Hava faresi kapalı"}

# kamera penceresindeki "Hareketler" ipucu listesi: (simge, hareket, ne yapar)
HELP_LINES = [
    ("🖐", "Açık avuç", "müziği oynat"),
    ("✊", "Yumruk", "müziği durdur"),
    ("👉 👈", "İşaret parmağı yana", "sonraki / önceki şarkı"),
    ("👍 👎", "Başparmak yukarı / aşağı", "ses aç / kıs (tut)"),
    ("👍👍 👎👎", "İki el başparmak yukarı / aşağı", "parlaklık artır / azalt (tut)"),
    ("✌️", "V işareti", "ekran görüntüsü"),
    ("🤟", "Üç parmak", "bu ne? (ekranı açıkla)"),
    ("👌", "OK işareti", "sesi kapat / aç"),
    ("🤘", "Rock işareti (0,5 sn)", "hava faresini aç (kapatmak için İKİ el rock; tık = diğer el yumruk)"),
    ("🙌", "İki el açık (1 sn)", "kontrolleri duraklat / devam"),
    ("👋", "El sallama (sağ-sol)", "JARVIS'i uyandır"),
    ("✊✊", "İki yumruk birlikte", "ekranı kilitle"),
    ("✌️✌️↔️", "İki el V işareti, uzaklaştır/yaklaştır", "holografik HUD büyür / küçülür"),
]
HELP_NOTE = "Hareketleri yarım saniye sabit tut. Parlaklık modundan çıkmak için avucunu aç ya da elini indir. Pencereyi büyütmek için görüntüye çift tıkla ya da \"Tam ekran\" düğmesine bas."

SHAPE_NAMES = {"open": "Açık avuç", "fist": "Yumruk", "thumb_up": "Başparmak yukarı",
               "thumb_down": "Başparmak aşağı", "victory": "V işareti", "zoom": "Zoom (parlaklık)", "three": "Üç parmak", "ok": "OK işareti", "rock": "Rock (fare modu)", "point_left": "İşaret ◀ sol", "point_right": "İşaret ▶ sağ", "other": "—"}

# el iskeleti cizgileri (onizleme penceresi icin)
_CONN = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
         (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17))


class _OneEuro:
    """Adaptif titreme filtresi: el yavas/dururken cok yumusatir (titreme yok), hizli gidince gecikme olmaz."""

    def __init__(self, mincutoff, beta, dcutoff=1.0):
        self.mincutoff, self.beta, self.dcutoff = mincutoff, beta, dcutoff
        self.x = None
        self.dx = 0.0
        self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t, x):
        if self.t is None:
            self.t, self.x = t, x
            return x
        dt = max(1e-3, t - self.t)
        dx = (x - self.x) / dt
        ad = self._alpha(self.dcutoff, dt)
        self.dx = ad * dx + (1.0 - ad) * self.dx
        a = self._alpha(self.mincutoff + self.beta * abs(self.dx), dt)
        self.x = a * x + (1.0 - a) * self.x
        self.t = t
        return self.x


# ══════════════════════════════════════════
#  0) WINDOWS FARE (sadece Windows; baska sistemde hicbir sey yapmaz)
# ══════════════════════════════════════════
def _os_screen():
    import ctypes
    u = ctypes.windll.user32
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def _os_mouse_move(nx, ny):
    if os.name != "nt":
        return
    try:
        import ctypes
        w, h = _os_screen()
        ctypes.windll.user32.SetCursorPos(int(max(0.0, min(1.0, nx)) * (w - 1)),
                                          int(max(0.0, min(1.0, ny)) * (h - 1)))
    except Exception as e:
        print("Fare hareketi hatasi:", e)


def _os_mouse_button(name):
    if os.name != "nt":
        return
    try:
        import ctypes
        me = ctypes.windll.user32.mouse_event
        if name == "mouse_down":
            me(0x0002, 0, 0, 0, 0)                      # sol tus basildi
        elif name == "mouse_up":
            me(0x0004, 0, 0, 0, 0)                      # sol tus birakildi
        elif name == "mouse_click":
            me(0x0002, 0, 0, 0, 0)                      # sol tik (bas + birak)
            me(0x0004, 0, 0, 0, 0)
        elif name == "mouse_rclick":
            me(0x0008, 0, 0, 0, 0)                      # sag tus basildi
            me(0x0010, 0, 0, 0, 0)                      # sag tus birakildi
    except Exception as e:
        print("Fare tiki hatasi:", e)


# ══════════════════════════════════════════
#  1) MOTOR: el noktalarindan olay uretir (kameradan bagimsiz)
# ══════════════════════════════════════════
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pinch_dist(lm):
    """Basparmak ucu ile isaret parmagi ucu arasi mesafe (avuc boyuna gore). Zoom ayari bunu okur."""
    size = _dist(lm[0], lm[9])
    return _dist(lm[4], lm[8]) / size if size > 1e-6 else 0.0


def classify(lm, loose=False):
    """21 noktadan el seklini bulur: 'open' (acik avuc), 'fist' (yumruk), 'thumb_up', 'thumb_down',
    'victory' (V isareti) ya da 'other'. Dort parmagin ucu bilege ne kadar uzak diye bakilir (el donse de calisir)."""
    wrist = lm[0]
    rs = []
    for tip, pip in zip(_TIPS, _PIPS):
        dp = _dist(lm[pip], wrist)
        if dp < 1e-6:
            return "other"
        rs.append(_dist(lm[tip], wrist) / dp)
    ext = sum(1 for r in rs if r >= EXT_RATIO)
    fold = sum(1 for r in rs if r <= FOLD_RATIO)
    # OK isareti: basparmak ucu isaret parmagi ucuna degiyor, diger uc parmak acik
    size0 = _dist(lm[0], lm[9])
    if size0 > 1e-6 and _dist(lm[4], lm[8]) / size0 < 0.3 \
            and rs[1] >= EXT_RATIO and rs[2] >= EXT_RATIO and rs[3] >= EXT_RATIO:
        return "ok"
    if ext == 4:
        return "open"
    if rs[0] >= EXT_RATIO and rs[1] >= EXT_RATIO and rs[2] <= FOLD_RATIO and rs[3] <= FOLD_RATIO:
        return "victory"
    if rs[0] >= EXT_RATIO and rs[1] >= EXT_RATIO and rs[2] >= EXT_RATIO and rs[3] <= FOLD_RATIO:
        return "three"                      # isaret + orta + yuzuk parmak acik
    if rs[0] >= EXT_RATIO and rs[3] >= EXT_RATIO and rs[1] <= FOLD_RATIO and rs[2] <= FOLD_RATIO:
        return "rock"                       # isaret + serce parmak acik, orta + yuzuk kapali (fare modu anahtari)
    if rs[0] >= 0.85 and rs[1] <= ZOOM_FOLD and rs[2] <= ZOOM_FOLD and rs[3] <= ZOOM_FOLD:
        # zoom: basparmak ve isaret parmagi (diger uc parmak kapali). Acikken aralari acik (L), kapaninca ucu uca gelir.
        size = _dist(lm[0], lm[9])
        if size > 1e-6 and _dist(lm[4], lm[5]) / size >= 0.5:
            if pinch_dist(lm) < (0.8 if loose else 0.6):      # loose: zaten zoom icindeyken esikler gevsek (ara konumlarda kopmasin)
                return "zoom"
            v1 = (lm[4][0] - lm[2][0], lm[4][1] - lm[2][1])
            v2 = (lm[8][0] - lm[5][0], lm[8][1] - lm[5][1])
            n1, n2 = math.hypot(*v1), math.hypot(*v2)
            if n1 >= 0.6 * size and n2 > 1e-6:          # basparmak gercekten acik olmali
                cosang = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
                if math.degrees(math.acos(cosang)) >= (15 if loose else 30) and rs[0] >= EXT_RATIO:
                    return "zoom"
    if rs[0] >= EXT_RATIO and rs[1] <= FOLD_RATIO and rs[2] <= FOLD_RATIO and rs[3] <= FOLD_RATIO:
        # sadece isaret parmagi acik: yana dogru gosteriyorsa sag / sol
        size = _dist(lm[0], lm[9])
        dx = lm[8][0] - lm[5][0]
        dy = lm[8][1] - lm[5][1]
        if size > 1e-6 and abs(dx) >= 0.5 * size and abs(dx) >= 1.3 * abs(dy):
            return "point_right" if dx > 0 else "point_left"
        return "other"
    if ext == 0 and fold >= 3:
        # yumruk mu, basparmak yukari/asagi mi? Basparmak acik ve dikey ise basparmak hareketi.
        size = _dist(lm[0], lm[9])                      # avuc boyu
        if size > 1e-6 and _dist(lm[4], lm[5]) / size >= THUMB_OUT:
            dx = lm[4][0] - lm[2][0]
            dy = lm[4][1] - lm[2][1]
            if abs(dy) >= 0.7 * size and abs(dy) >= 0.9 * abs(dx):
                return "thumb_up" if dy < 0 else "thumb_down"     # goruntude yukari = y kucuk
        return "fist"
    return "other"


def palm_center(lm):
    return (sum(lm[i][0] for i in _PALM) / len(_PALM),
            sum(lm[i][1] for i in _PALM) / len(_PALM))


def is_closed_hand(lm):
    """Tik eli icin gevsek yumruk testi: 4 parmak da kapali (isaret parmagi acik olan el = imlec eli, yumruk degil)."""
    wrist = lm[0]
    rs = []
    for tip, pip in zip(_TIPS, _PIPS):
        dp = _dist(lm[pip], wrist)
        if dp < 1e-6:
            return False
        rs.append(_dist(lm[tip], wrist) / dp)
    closed = [r < MOUSE_CLOSED_RATIO for r in rs]
    return all(closed)


class GestureEngine:
    """update(t, lm, lm2=None) -> olay listesi. lm / lm2: 21 (x, y) noktasi (0..1, ayna cevrilmis kare) ya da None.
    Olaylar: 'play', 'pause', 'next', 'prev', 'vol_up', 'vol_down', 'screenshot', 'freeze', 'unfreeze'."""

    def __init__(self):
        self.zoom_active = False     # zoom (parlaklik) modu acik mi: acikken sekil aramaz, sadece mesafeye bakar
        self.zoom_ref = None         # zoom ayarinda son adim mesafesi
        self.zd = 0.0                # yumusatilmis basparmak-isaret mesafesi
        self.world_active = False    # iki el V isareti: holografik HUD acik mi
        self.world_ref = None
        self.lock_since = None       # iki yumruk ne zamandir tutuluyor
        self.lock_fired = False
        self.lock_cd = 0.0
        self.wave_cd = 0.0
        self.mouse_active = False    # hava faresi modu acik mi
        self.mouse_pos = None        # imlec konumu (ekranin 0..1 orani), yumusatilmis
        self.mouse_down = False      # sol tus su an basili mi
        self.cd = {}                 # sekil -> yeniden calisabilecegi an
        self.frozen = False          # iki el hareketiyle duraklatildi mi (reset'ten etkilenmez)
        self.reset()

    def reset(self):
        self.trail = deque()                         # (t, x, y) avuc merkezi gecmisi
        self.labels = deque(maxlen=SMOOTH_FRAMES)
        self.label = None                            # yumusatilmis el sekli
        self.label_since = 0.0
        self.last_fired = None                       # son calisan tutma hareketi
        self.armed = True                            # kaydirmadan sonra el durana kadar False
        self.block_until = 0.0
        self.still_since = None
        self.lost_since = None
        self._br_label = None                        # iki el basparmak: "thumb_up"/"thumb_down"/None
        self._br_since = 0.0
        self._br_last = 0.0
        self.vol_last = 0.0                          # son ses degisimi (tekrar icin)
        self.shot_until = 0.0
        self.two_hist = deque(maxlen=SMOOTH_FRAMES)  # iki el acik mi gecmisi
        self.two_since = None
        self.two_fired = False

    # -- yardimcilar --
    def _recent(self, t, win):
        return [p for p in self.trail if p[0] >= t - win]

    def _extent(self, t, win):
        pts = self._recent(t, win)
        if len(pts) < 2:
            return 0.0
        xs = [p[1] for p in pts]
        ys = [p[2] for p in pts]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    def _swipe(self, t):
        pts = self._recent(t, SWIPE_WIN)
        if len(pts) < 3:
            return None
        # hareketin basladigi kareyi bul (oncesindeki sabit kareler hizi dusurmesin)
        start = next((i for i in range(len(pts) - 1)
                      if abs(pts[i + 1][1] - pts[i][1]) > 0.004), None)
        if start is None:
            return None
        seg = pts[start:]
        dur = seg[-1][0] - seg[0][0]
        dx = seg[-1][1] - seg[0][1]
        dy = seg[-1][2] - seg[0][2]
        if dur < SWIPE_MIN_SEC or abs(dx) < SWIPE_DIST or abs(dy) > 0.6 * abs(dx):
            return None
        if abs(dx) / dur < SWIPE_SPEED:            # yavas surukleme / yavas geri cekme: kaydirma degil
            return None
        moving = [seg[i + 1][1] - seg[i][1] for i in range(len(seg) - 1)
                  if abs(seg[i + 1][1] - seg[i][1]) > 0.004]
        if len(moving) < 3:
            return None
        same = sum(1 for s in moving if s * dx > 0)
        if same < 0.75 * len(moving):              # sag-sol sallanma: kaydirma degil
            return None
        return "next" if dx > 0 else "prev"

    def _two_hands(self, t, lm, lm2):
        """Iki elin birlikte yaptigi 3 ayri poz, birbirine karismasin diye sekle gore tamamen ayrilir:
          - IKI YUMRUK (sabit, ~0.6 sn)          -> ekrani kilitle ("lock")
          - IKI V ISARETI (uzaklastir/yaklastir) -> holografik HUD ac/ayarla ("world_in"/"world_out"/"world_exit")
          - IKI ACIK AVUC (sabit, ~1 sn)         -> duraklat / devam ("freeze"/"unfreeze")
        """
        events = []
        if lm is None or lm2 is None:
            # Eller ayrilsa/kaybolsa bile HUD oldugu buyuklukte KALIR (kullanici ozellikle istedi).
            # Sadece YENIDEN iki V isaretiyle kucultulunce ya da sesli "haritayi kapat" deyince kapanir.
            self.lock_since = None
            self.lock_fired = False
            self.two_hist.clear()
            self.two_since = None
            self.two_fired = False
            return events

        shape1, shape2 = classify(lm), classify(lm2)

        # ── IKI YUMRUK: kilitle ──
        if shape1 == "fist" and shape2 == "fist":
            if self.lock_since is None:
                self.lock_since = t
            if not self.lock_fired and t - self.lock_since >= LOCK_HOLD and t >= self.lock_cd:
                self.lock_fired = True
                self.lock_cd = t + LOCK_COOLDOWN
                events.append("lock")
            return events
        self.lock_since = None
        self.lock_fired = False

        # ── IKI V ISARETI: holografik HUD (acik avuc duraklatmasiyla asla karismaz, farkli sekil) ──
        both_v = shape1 == "victory" and shape2 == "victory"
        if self.world_active:
            # Baska bir sey yapiyorsan (V isaretinden cikmis olsan bile) HUD KAPANMAZ, sadece beklemede kalir.
            # Kapatmak icin: sesli "haritayi kapat" de (jarvis_voice.py -> hud_close()).
            if not both_v:
                return events
            dist = _dist(palm_center(lm), palm_center(lm2))
            if self.world_ref is None:
                self.world_ref = dist
            elif dist - self.world_ref >= WORLD_STEP:
                events.append("world_in")
                self.world_ref += WORLD_STEP
            elif self.world_ref - dist >= WORLD_STEP:
                events.append("world_out")
                self.world_ref -= WORLD_STEP
            return events
        if both_v and _dist(palm_center(lm), palm_center(lm2)) >= TWO_HAND_SEP:
            self.world_active = True
            self.world_ref = None
            self.two_hist.clear()
            self.two_since = None
            return events

        # ── IKI ACIK AVUC, YERINDE SABIT: duraklat / devam ──
        both_open = shape1 == "open" and shape2 == "open"
        sep_ok = both_open and _dist(palm_center(lm), palm_center(lm2)) >= TWO_HAND_SEP
        self.two_hist.append(sep_ok)
        smooth = sum(self.two_hist) * 2 > len(self.two_hist)
        if not smooth:
            self.two_since = None
            return events
        if self.two_since is None:
            self.two_since = t
        if not self.two_fired and t - self.two_since >= TWO_HAND_HOLD:
            self.frozen = not self.frozen
            self.two_fired = True
            events.append("freeze" if self.frozen else "unfreeze")
            self.trail.clear()
            self.last_fired = None
            self.block_until = t + COOLDOWN
        return events

    # -- hava faresi --
    def _mouse_start(self, t):
        self.mouse_active = True
        self.mouse_pos = None
        self.mouse_down = False
        self._m_pinch = 0
        self._m_rock = None
        self._m_rock2 = None               # iki el rock sayaci
        self._m_v = None                   # sag tik V isareti sayaci
        self._m_rock_cd = t + 1.5          # acar acmaz hemen kapanmasin
        self._m_rock_ok = False            # rock pozundan ONCE cikilmadan kapatma hareketi sayilmaz
        self._m_rcd = 0.0
        self._m_lost = None
        self._m_r = deque()                # (t, parmak boyu orani) gecmisi: itme/bukme algilamak icin
        self._m_ph = deque()               # (t, imlec konumu) gecmisi: itme baslarken geri sarmak icin
        self._m_push = False               # itme tiki yapildi, parmak geri donene kadar yenisi yok
        self._m_push_base = 1.0
        self._m_ccd = 0.0
        self._m_frozen = False
        self._m_fx = _OneEuro(MOUSE_MINCUT, MOUSE_BETA)     # imlec titreme filtreleri (x ve y)
        self._m_fy = _OneEuro(MOUSE_MINCUT, MOUSE_BETA)
        self._m_dw_anchor = None           # bekleyerek tik: imlecin durdugu nokta
        self._m_dw_since = 0.0
        self._m_dw_done = False
        self._m_labels = deque(maxlen=SMOOTH_FRAMES)
        self.trail.clear()
        self.last_fired = None

    def _mouse_stop(self, events):
        if self.mouse_down:
            events.append("mouse_up")      # basili kalmasin
            self.mouse_down = False
        self.mouse_active = False
        self.mouse_pos = None
        events.append("mouse_off")
        self.trail.clear()
        self.label = None
        self.labels.clear()
        self.last_fired = "rock"           # rock hala tutuluyorsa hemen tekrar acilmasin
        self.block_until = 0.0

    def _mouse_update(self, t, lm, lm2=None):
        """Fare modu aciksa tum diger hareketler durur; sadece imlec ve tik calisir."""
        events = []
        if lm is None:
            if self._m_lost is None:
                self._m_lost = t
            if self.mouse_down and t - self._m_lost > 0.4:
                events.append("mouse_up")
                self.mouse_down = False
            if t - self._m_lost > MOUSE_LOST_OFF:
                self._mouse_stop(events)
            return events
        self._m_lost = None

        # kapatma: rock isaretini 1 sn tut
        self._m_labels.append(classify(lm))
        smooth = Counter(self._m_labels).most_common(1)[0][0]
        cx, cy = palm_center(lm)
        self.trail.append((t, cx, cy))
        while self.trail and self.trail[0][0] < t - 1.5:
            self.trail.popleft()
        if MOUSE_OFF_TWO_HANDS:
            if lm2 is not None and classify(lm) == "rock" and classify(lm2) == "rock" and t >= self._m_rock_cd:
                if self._m_rock2 is None:
                    self._m_rock2 = t
                elif t - self._m_rock2 >= MOUSE_OFF_TWO:
                    self._mouse_stop(events)
                    return events
                return events                  # iki el rock tutarken imlec oynamasin
            self._m_rock2 = None
        if smooth == "rock" and not MOUSE_OFF_TWO_HANDS:
            # Isaret parmagiyla gosterirken serce parmak yarim acik kalinca "rock" gibi gorunebilir.
            # O yuzden: once rock pozundan cikmis olmali + el SABIT durmali + yeterince uzun tutulmali.
            if self._m_rock is None:
                self._m_rock = t
            still = self._extent(t, 1.0) < STILL_MAX * 1.5
            if not still:
                self._m_rock = t           # el oynuyorsa sayac sifirlanir
            elif self._m_rock_ok and t - self._m_rock >= MOUSE_OFF_HOLD and t >= self._m_rock_cd:
                self._mouse_stop(events)
                return events
            return events                  # rock tutarken imlec oynamasin
        self._m_rock = None
        self._m_rock_ok = True             # rock pozundan cikildi, artik kapatma hareketi gecerli

        click_hand = None
        if MOUSE_CLICK_SECOND:
            # iki el varsa: yumruk olan el TIK elidir, diger el imlec elidir
            if lm2 is not None and is_closed_hand(lm) and not is_closed_hand(lm2):
                lm, lm2 = lm2, lm
            if lm2 is None:
                click_hand = None
            elif is_closed_hand(lm2):
                click_hand = "fist"
            else:
                click_hand = classify(lm2)

        size = _dist(lm[0], lm[9])
        if size < 1e-6:
            return events
        pd = _dist(lm[4], lm[8]) / size                 # basparmak - isaret
        pd2 = _dist(lm[4], lm[12]) / size               # basparmak - orta (sag tik)
        if MOUSE_CLICK_SECOND:
            pd, pd2 = 1.0, 1.0                          # imlec eli tiklamaz, imlec hic donmaz

        # itme / bukme tiki: isaret parmaginin goruntudeki boyu (uc - kok), avuc boyuna oranla, aniden kisalirsa
        # (parmak kameraya dogru itilince ya da bukulunce kisa gorunur) = sol tik
        push_freeze = False
        if MOUSE_PUSH_CLICK and not MOUSE_CLICK_SECOND:
            r_now = _dist(lm[8], lm[5]) / size
            self._m_r.append((t, r_now))
            while self._m_r and self._m_r[0][0] < t - 1.2:
                self._m_r.popleft()
            olds = [r for (tt, r) in self._m_r if tt <= t - 0.15]
            recent = [r for (tt, r) in self._m_r if tt > t - 0.2]
            if olds and recent:
                base = max(olds)
                r_s = sum(recent) / len(recent)
                if base >= 0.5:
                    ratio = r_s / base
                    push_freeze = self._m_push or ratio < MOUSE_PUSH_FREEZE
                    if push_freeze and not self._m_frozen and self.mouse_pos is not None:
                        # itme basladi: imleci ~0.3 sn oncesine geri sar (parmak kayarken oynamis olabilir)
                        for (tt, pp) in self._m_ph:
                            if tt >= t - 0.3:
                                self.mouse_pos = pp
                                break
                    self._m_frozen = push_freeze
                    if not self._m_push and ratio < MOUSE_PUSH_ON and t >= self._m_ccd:
                        events.append("mouse_click")
                        self._m_push = True
                        self._m_push_base = base
                        self._m_ccd = t + MOUSE_PUSH_CD
                    elif self._m_push and r_s > MOUSE_PUSH_OFF * self._m_push_base:
                        self._m_push = False

        # imlec: isaret parmagi ucu. Tik yaklasirken (pinch) donar; basili tutarken (surukleme) oynar.
        if (pd >= MOUSE_FREEZE or self.mouse_down) and not push_freeze:
            x0, x1, y0, y1 = MOUSE_BOX
            tx = max(0.0, min(1.0, (lm[8][0] - x0) / (x1 - x0)))
            ty = max(0.0, min(1.0, (lm[8][1] - y0) / (y1 - y0)))
            nx, ny = self._m_fx(t, tx), self._m_fy(t, ty)
            if self.mouse_pos is None or _dist((nx, ny), self.mouse_pos) > MOUSE_DEADZONE:
                self.mouse_pos = (nx, ny)
            self._m_ph.append((t, self.mouse_pos))
            while self._m_ph and self._m_ph[0][0] < t - 1.0:
                self._m_ph.popleft()

            # bekleyerek tik (MOUSE_DWELL > 0 ise): imleci bir yerde tutunca tek tik
            if MOUSE_DWELL > 0 and not self.mouse_down and pd >= MOUSE_FREEZE:
                if self._m_dw_anchor is None or _dist(self.mouse_pos, self._m_dw_anchor) > MOUSE_DWELL_RADIUS:
                    self._m_dw_anchor = self.mouse_pos
                    self._m_dw_since = t
                    self._m_dw_done = False
                elif not self._m_dw_done and t - self._m_dw_since >= MOUSE_DWELL:
                    events.append("mouse_click")
                    self._m_dw_done = True

        if MOUSE_CLICK_SECOND:
            # diger el yumruk = sol tus basili (birakinca tik, tutarsan surukleme); V = sag tik
            if click_hand == "fist":
                self._m_pinch += 1
                if not self.mouse_down and self._m_pinch >= MOUSE_CLICK_FRAMES:
                    self.mouse_down = True
                    events.append("mouse_down")
            else:
                self._m_pinch = 0
                if self.mouse_down:
                    self.mouse_down = False
                    events.append("mouse_up")
                if click_hand == "victory":
                    if self._m_v is None:
                        self._m_v = t
                    elif t - self._m_v >= MOUSE_RCLICK_HOLD and t >= self._m_rcd:
                        self._m_rcd = t + MOUSE_RCLICK_CD
                        self._m_v = None
                        events.append("mouse_rclick")
                else:
                    self._m_v = None
            return events

        # sol tik / surukleme
        if not self.mouse_down:
            if pd < MOUSE_PINCH_ON:
                self._m_pinch += 1
                if self._m_pinch >= MOUSE_PINCH_FRAMES:
                    self.mouse_down = True
                    events.append("mouse_down")
            else:
                self._m_pinch = 0
        elif pd > MOUSE_PINCH_OFF:
            self.mouse_down = False
            self._m_pinch = 0
            events.append("mouse_up")

        # sag tik: basparmak + orta parmak (sol tik pinch'i yokken)
        if not self.mouse_down and pd >= MOUSE_PINCH_OFF and pd2 < MOUSE_RCLICK and t >= self._m_rcd:
            self._m_rcd = t + MOUSE_RCLICK_CD
            events.append("mouse_rclick")
        return events

    def _wave(self, t):
        """Acik el, yerinde kisa kisa sag-sola sallaniyor mu (el sallama / merhaba)?"""
        pts = self._recent(t, WAVE_WIN)
        if len(pts) < 6:
            return False
        xs = [p[1] for p in pts]
        if max(xs) - min(xs) < 0.06 or max(xs) - min(xs) > 0.4:   # cok kucuk ya da kaydirma kadar genis degil
            return False
        ys = [p[2] for p in pts]
        if max(ys) - min(ys) > 0.18:          # yukari asagi fazla oynuyorsa sallama degil
            return False
        diffs = [xs[i + 1] - xs[i] for i in range(len(xs) - 1) if abs(xs[i + 1] - xs[i]) > 0.01]
        if len(diffs) < 4:
            return False
        rev = sum(1 for i in range(len(diffs) - 1) if diffs[i] * diffs[i + 1] < 0)
        return rev >= WAVE_MIN_REV

    # -- ana islev --
    def update(self, t, lm, lm2=None):
        events = []
        if self.mouse_active:
            self.lost_since = None if lm is not None else (self.lost_since or t)
            return self._mouse_update(t, lm, lm2)
        if lm is None:
            if self.lost_since is None:
                self.lost_since = t
            if t - self.lost_since > LOST_RESET:
                self.reset()
                self.lost_since = t
            else:
                self.two_hist.append(False)
            self.two_fired = False if lm is None else self.two_fired
            return events
        self.lost_since = None

        # el sallama (uyandirma): her sekilde calisir, cooldown/bloklamadan etkilenmez
        if t >= self.wave_cd and self._wave(t):
            self.wave_cd = t + WAVE_COOLDOWN_G
            events.append("wake")

        # iki el: sadece duraklat/devam mantigi calisir, tek el hareketleri beklemeye alinir
        if lm2 is not None or self.two_fired or self.world_active or any(self.two_hist):
            events += self._two_hands(t, lm, lm2)
            if lm2 is not None:
                self.trail.clear()
                self.labels.clear()
                self.label = None
                # iki el basparmak yukari = parlaklik artar, iki el basparmak asagi = azalir
                if not self.frozen:
                    c1, c2 = classify(lm), classify(lm2)
                    cur = c1 if (c1 == c2 and c1 in ("thumb_up", "thumb_down")) else None
                    if cur != self._br_label:
                        self._br_label = cur
                        self._br_since = t
                        self._br_last = t
                    elif cur and t - self._br_since >= BRIGHT_HOLD and t - self._br_last >= BRIGHT_REPEAT:
                        events.append("bright_up" if cur == "thumb_up" else "bright_down")
                        self._br_last = t
                return events
        if self.frozen:
            return events

        cx, cy = palm_center(lm)
        self.trail.append((t, cx, cy))
        while self.trail and self.trail[0][0] < t - 1.5:
            self.trail.popleft()

        self.labels.append(classify(lm, loose=(self.label == "zoom")))
        smooth = Counter(self.labels).most_common(1)[0][0]
        if smooth != self.label:
            self.label = smooth
            self.label_since = t
        if self.label == "other" and t - self.label_since >= 0.3:
            self.last_fired = None                   # hareketler arasi gecis: ayni hareket yeniden calisabilir

        # zoom modu: bir kere acilinca parmaklar kapanip sekil bozulsa da mod DEVAM eder.
        # Cikis: eli indir (kaybolsun) ya da acik avuc yap.
        if self.zoom_active:
            if self.label == "open" and t - self.label_since >= 0.3:
                self.zoom_active = False
                self.zoom_ref = None
                self.last_fired = "open"          # cikarken "oynat" calismasin
                return events
            d = pinch_dist(lm)
            self.zd = d if self.zoom_ref is None else 0.5 * self.zd + 0.5 * d
            if self.zoom_ref is None:
                self.zoom_ref = self.zd
            elif self.zd - self.zoom_ref >= ZOOM_STEP:
                events.append("bright_up")
                self.zoom_ref += ZOOM_STEP
            elif self.zoom_ref - self.zd >= ZOOM_STEP:
                events.append("bright_down")
                self.zoom_ref -= ZOOM_STEP
            return events
        if ZOOM_ENABLED and self.label == "zoom" and t - self.label_since >= ZOOM_HOLD:
            self.zoom_active = True
            self.zoom_ref = None
            self.zd = pinch_dist(lm)
            return events

        if t < self.block_until:
            return events

        # kaydirmadan sonra: el durana kadar yeni hareket yok (geri donus hareketi "onceki" sayilmasin)
        if not self.armed:
            if self._extent(t, REARM_STILL) < STILL_MAX * 0.5:
                if self.still_since is None:
                    self.still_since = t
                elif t - self.still_since >= REARM_STILL:
                    self.armed = True
                    self.still_since = None
                    self.label_since = t
            else:
                self.still_since = None
            return events

        # kaydirma (yumruk, basparmak ve V haric)
        if self.label not in NO_SWIPE:
            sw = self._swipe(t)
            if sw:
                events.append(sw)
                self.block_until = t + COOLDOWN
                self.armed = False
                self.still_since = None
                self.last_fired = None
                self.label_since = t
                return events

        # ses: basparmak yukari / asagi (tutuldukca tekrar eder)
        if self.label in ("thumb_up", "thumb_down"):
            if t - self.label_since >= VOL_HOLD and self._extent(t, VOL_HOLD) < STILL_MAX \
                    and t - self.vol_last >= VOL_REPEAT:
                events.append("vol_up" if self.label == "thumb_up" else "vol_down")
                self.vol_last = t
            return events

        # isaret parmagi yana: sag = sonraki, sol = onceki (tutulunca; tutuldukca yavasca tekrar eder)
        if self.label in ("point_left", "point_right"):
            held = t - self.label_since >= HOLD_SEC
            if held and self._extent(t, HOLD_SEC) < STILL_MAX and \
                    (self.label != self.last_fired or t - self.vol_last >= POINT_REPEAT):
                events.append("next" if self.label == "point_right" else "prev")
                self.last_fired = self.label
                self.vol_last = t
            return events

        # tutma hareketleri: acik avuc = oynat, yumruk = durdur, V = ekran goruntusu,
        # uc parmak = "bu ne?", rock = sessize al / ac
        if self.label in HOLD_EVENTS:
            held = t - self.label_since >= HOLD_SEC
            if held and self._extent(t, HOLD_SEC) < STILL_MAX and self.label != self.last_fired:
                if t >= self.cd.get(self.label, 0.0):
                    events.append(HOLD_EVENTS[self.label])
                    self.cd[self.label] = t + HOLD_COOLDOWN.get(self.label, 0.0)
                    if HOLD_EVENTS[self.label] == "mouse_on":
                        self._mouse_start(t)
                self.last_fired = self.label
        return events


# ══════════════════════════════════════════
#  2) KONTROLCU: kamera + MediaPipe
# ══════════════════════════════════════════
def _download_model(say=None):
    """Model dosyasini bir kez indirir. (basarili_mi, hata_mesaji)"""
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        return True, ""
    try:
        import requests
        if say:
            say("El tanıma modeli indiriliyor, birkaç saniye sürecek.")
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = MODEL_PATH + ".part"
        with requests.get(MODEL_URL, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        if os.path.getsize(tmp) < 1_000_000:
            raise RuntimeError("indirilen dosya cok kucuk")
        os.replace(tmp, MODEL_PATH)
        return True, ""
    except Exception as e:
        print("Model indirme hatasi:", type(e).__name__, e)
        return False, "El tanıma modeli indirilemedi. İnternet bağlantını kontrol et."


class GestureController:
    """actions: {'play': fn, 'pause': fn, 'next': fn, 'prev': fn, 'vol_up': fn, ...}
    on_event(isim): geri bildirim icin.
    on_frame(rgb_bytes, genislik, yukseklik, el_sekli_yazisi): canli kamera penceresi icin.
    Sadece self.preview True iken cagrilir (kapaliyken kare cizilmez, islemci harcanmaz)."""

    def __init__(self, actions, on_event=None, on_stop=None, on_frame=None):
        self.actions = actions
        self.on_event = on_event
        self.on_stop = on_stop
        self.on_frame = on_frame
        self.preview = False
        self._last_ev = ("", 0.0)
        self._thread = None
        self._stop = threading.Event()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, say=None):
        """(basladi_mi, kullaniciya_soylenecek_mesaj). Kamera ve model hazirsa arka planda calisir."""
        if self.running:
            return True, "El modu zaten açık."
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision
        except Exception as e:
            print("El modu import hatasi:", type(e).__name__, e)
            return False, ("El modu için eksik kütüphane var. Terminale şunu yaz: "
                           "pip install mediapipe opencv-python")
        ok, msg = _download_model(say)
        if not ok:
            return False, msg
        try:
            idx = _camera_index()
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                return False, "Kamerayı açamadım. Başka bir uygulama kullanıyor olabilir."
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            opts = vision.HandLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=vision.RunningMode.VIDEO, num_hands=2,
                min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5)
            landmarker = vision.HandLandmarker.create_from_options(opts)
        except Exception as e:
            print("El modu baslatma hatasi:", type(e).__name__, e)
            try:
                cap.release()
            except Exception:
                pass
            return False, "El modunu başlatamadım. Ayrıntı konsolda yazıyor."
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(cv2, mp, cap, landmarker), daemon=True)
        self._thread.start()
        return True, ("El modu açık.")

    def stop(self):
        self._stop.set()
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=2.0)

    def _dispatch(self, name):
        if name in ("mouse_down", "mouse_up", "mouse_click", "mouse_rclick"):
            _os_mouse_button(name)                       # tik: ekranda yazi gostermeden dogrudan yap
            return
        self._last_ev = (LABELS.get(name, name), time.time())
        fn = self.actions.get(name)
        if fn is not None:
            threading.Thread(target=self._safe, args=(fn, name), daemon=True).start()
        if self.on_event:
            try:
                self.on_event(name)
            except Exception:
                pass

    @staticmethod
    def _safe(fn, name):
        try:
            fn()
        except Exception as e:
            print("El hareketi komutu hatasi (%s):" % name, e)

    def _send_frame(self, cv2, frame, hands, engine):
        """Iskelet cizilmis kucuk kareyi onizleme penceresine yollar."""
        try:
            h, w = frame.shape[:2]
            img = frame.copy()
            if HAND_ONLY_PREVIEW:
                img[:] = (14, 10, 6)                      # kamera goruntusunu sil, sadece koyu zemin kalsin
            color = (0, 200, 255) if not engine.frozen else (120, 120, 120)
            for hand in hands:
                pts = [(int(x * w), int(y * h)) for x, y in hand]
                for a, b in _CONN:
                    cv2.line(img, pts[a], pts[b], color, 2)
                for p in pts:
                    cv2.circle(img, p, 3, (255, 255, 255), -1)
            img = cv2.resize(img, (PREVIEW_W, PREVIEW_H))
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            if engine.mouse_active:
                info = "HAVA FARESI"
            elif engine.frozen:
                info = "DURAKLATILDI (iki eli aç)"
            elif not hands:
                info = "El yok"
            elif len(hands) > 1:
                info = "İki el"
            else:
                info = SHAPE_NAMES.get(engine.label, "—")
            if time.time() - self._last_ev[1] < 2.0:
                info += "  ·  " + self._last_ev[0]
            self.on_frame(rgb.tobytes(), PREVIEW_W, PREVIEW_H, info)
        except Exception as e:
            print("Onizleme hatasi:", e)

    def _loop(self, cv2, mp, cap, landmarker):
        engine = GestureEngine()
        period = 1.0 / FPS
        last_ts = 0
        fails = 0
        dbg_t = 0.0
        reason = ""
        try:
            while not self._stop.is_set():
                t0 = time.time()
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails >= 30:
                        reason = "Kamera görüntüsü kesildi, el modu kapandı."
                        break
                    time.sleep(0.1)
                    continue
                fails = 0
                frame = cv2.flip(frame, 1)                       # ayna: sagin = goruntunun sagi
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                ts = max(last_ts + 1, int(time.monotonic() * 1000))
                last_ts = ts
                res = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
                hands = [[(p.x, p.y) for p in h] for h in (res.hand_landmarks or [])]
                lm = hands[0] if hands else None
                lm2 = hands[1] if len(hands) > 1 else None
                now = time.time()
                for ev in engine.update(now, lm, lm2):
                    self._dispatch(ev)
                if engine.mouse_active and engine.mouse_pos is not None:
                    _os_mouse_move(*engine.mouse_pos)
                if self.preview and self.on_frame:
                    self._send_frame(cv2, frame, hands, engine)
                if DEBUG and now - dbg_t > 1.0:
                    dbg_t = now
                    print("el:", engine.label if lm else "yok")
                period = 1.0 / (MOUSE_FPS if engine.mouse_active else FPS)   # fare modunda daha akici
                rest = period - (time.time() - t0)
                if rest > 0:
                    self._stop.wait(rest)
        except Exception as e:
            print("El modu dongu hatasi:", type(e).__name__, e)
            reason = "El modunda bir hata oldu, kapandı."
        finally:
            if engine.mouse_down:
                _os_mouse_button("mouse_up")             # sol tus basili kalmasin
            try:
                cap.release()
            except Exception:
                pass
            try:
                landmarker.close()
            except Exception:
                pass
            if reason and self.on_stop:
                try:
                    self.on_stop(reason)
                except Exception:
                    pass


# ══════════════════════════════════════════
#  3) TEK BASINA TEST:  python jarvis_gesture.py
# ══════════════════════════════════════════
def _pick_camera():
    """python jarvis_gesture.py --cameras : kameralari sirayla gosterir, dogru olanda Enter'a bas."""
    import cv2
    print("Her kamera birkac saniye gosterilir. DOGRU kamerada ENTER'a bas (kaydedilir), "
          "sonrakine gecmek icin baska bir tusa bas, cikmak icin Esc.")
    for i in range(6):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
        if not cap.isOpened():
            cap.release()
            continue
        t0 = time.time()
        chosen = None
        while time.time() - t0 < 6:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.putText(frame, f"Kamera {i}: dogruysa ENTER, degilse baska tus", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.imshow("Kamera sec", frame)
            k = cv2.waitKey(30) & 0xFF
            if k in (13, 10):
                chosen = i
                break
            if k == 27:
                cap.release()
                cv2.destroyAllWindows()
                return
            if k != 255:
                break
        cap.release()
        if chosen is not None:
            try:
                os.makedirs(os.path.dirname(CAMERA_FILE), exist_ok=True)
                with open(CAMERA_FILE, "w", encoding="utf-8") as f:
                    f.write(str(chosen))
                print(f"Kamera {chosen} kaydedildi ({CAMERA_FILE}). JARVIS'i yeniden baslat.")
            except Exception as e:
                print("Kaydedilemedi:", e, "-> jarvis_gesture.py icindeki CAMERA_INDEX =", chosen, "yap.")
            cv2.destroyAllWindows()
            return
    cv2.destroyAllWindows()
    print("Kamera secilmedi.")


if __name__ == "__main__":
    import sys
    if "--cameras" in sys.argv:
        _pick_camera()
        sys.exit(0)
    import cv2
    import numpy as np

    latest = {"f": None, "info": ""}

    def _frame(data, w, h, info):
        latest["f"] = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
        latest["info"] = info

    def _show(name):
        print(time.strftime("%H:%M:%S"), "->", LABELS.get(name, name))

    ctrl = GestureController(actions={}, on_event=_show, on_frame=_frame,
                             on_stop=lambda r: print(r))
    ctrl.preview = True
    ok, msg = ctrl.start(say=print)
    print(msg)
    if ok:
        print("Çıkmak için pencerede q ya da Esc'ye bas.")
        while ctrl.running:
            f = latest["f"]
            if f is not None:
                img = cv2.cvtColor(f, cv2.COLOR_RGB2BGR).copy()
                cv2.putText(img, latest["info"].encode("ascii", "replace").decode(), (8, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.imshow("JARVIS el modu testi", img)
            k = cv2.waitKey(30) & 0xFF
            if k in (27, ord("q")):
                break
        ctrl.stop()
        cv2.destroyAllWindows()