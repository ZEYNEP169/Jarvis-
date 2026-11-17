# -*- coding: utf-8 -*-
"""
JARVIS SARKI SOZLERI
====================
Zamanlanmis (senkron) sozleri LRCLIB'den (lrclib.net, ucretsiz, anahtar gerektirmez) getirir.
Adadaki (jarvis_island.py) soz modu bu dosyayi kullanir.

  lookup(title, artist, duration) -> (durum, satirlar)
     durum: "loading" (araniyor) | "ok" (bulundu) | "none" (bulunamadi)
     satirlar: [(saniye, "soz satiri"), ...]   (saniyeye gore sirali)
  index_at(satirlar, konum_sn)    -> su an okunan satirin sirasi (-1: henuz baslamadi)

Arama arka planda yapilir, adayi dondurmaz. Sonuclar bellekte onbelleklenir
(ayni sarki icin tekrar internete cikilmaz). Sadece sarki adi, sanatci ve sure gonderilir.
"""

import re
import time
import threading

BASE = "https://lrclib.net/api"
TIMEOUT = 6                  # sn: bir istek icin en fazla bekleme
RETRY_AFTER = 60             # sn: ag hatasi olursa bu kadar sonra tekrar dene
MAX_CACHE = 60
USER_AGENT = "JARVIS-Island/1.0 (kisisel asistan)"

_cache = {}                  # anahtar -> {"status", "lines", "ts", "err"}
_lock = threading.Lock()

_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_WORD_TS = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")


# ══════════════════════════════════════════
#  LRC ayristirma
# ══════════════════════════════════════════
def parse_lrc(text):
    """LRC metnini [(saniye, satir), ...] listesine cevirir.
    [00:12.34] soz   |   [00:10.00][00:50.00] tekrar eden soz   |   [ar:Sanatci] gibi etiketler atlanir."""
    out = []
    for raw in str(text or "").splitlines():
        stamps = list(_TS.finditer(raw))
        if not stamps:
            continue
        lyric = _WORD_TS.sub("", raw[stamps[-1].end():]).strip()
        for m in stamps:
            frac = m.group(3) or "0"
            sec = int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / (10 ** len(frac))
            out.append((sec, lyric))
    out.sort(key=lambda x: x[0])
    return out


def index_at(lines, pos):
    """pos (saniye) aninda okunan satirin sirasi. Ilk satirdan once -1 doner."""
    lo, hi = 0, len(lines)
    while lo < hi:
        mid = (lo + hi) // 2
        if lines[mid][0] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


# ══════════════════════════════════════════
#  Baslik / sanatci temizleme
# ══════════════════════════════════════════
_NOISE_PAREN = re.compile(
    r"\s*[\(\[][^)\]]*(?:feat|ft\.|with |remaster|live|version|edit|official|lyric|video|"
    r"audio|mix|explicit|karaoke|sped|slowed)[^)\]]*[\)\]]", re.I)
_NOISE_DASH = re.compile(
    r"\s+-\s+(?:\d{4}\s+)?(?:remaster\w*|.*\bversion\b|.*\bremaster\w*|radio edit|live\b|mono|stereo).*$", re.I)


def clean(title, artist):
    title = str(title or "").strip()
    artist = str(artist or "").strip()
    if not artist and " - " in title:        # "Sanatci - Sarki" (YouTube / dosya adi)
        artist, title = [s.strip() for s in title.split(" - ", 1)]
    title = _NOISE_PAREN.sub("", title)
    title = _NOISE_DASH.sub("", title).strip()
    artist = re.split(r"\s*(?:,|;|&|/|\bfeat\.?|\bft\.?|\bx\b)\s*", artist, maxsplit=1, flags=re.I)[0].strip()
    return title, artist


# ══════════════════════════════════════════
#  Internetten getirme
# ══════════════════════════════════════════
def _http_get(path, params):
    """JSON doner; 404 ise None; ag hatasinda istisna firlatir."""
    import requests
    r = requests.get(BASE + path, params=params, timeout=TIMEOUT,
                     headers={"User-Agent": USER_AGENT})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _pick(results, duration):
    """Arama sonuclarindan senkron sozu olan ve suresi en yakin olani sec."""
    if not isinstance(results, list):
        return None
    cands = [x for x in results if isinstance(x, dict) and x.get("syncedLyrics")]
    if not cands:
        return None
    if duration and duration > 0:
        cands.sort(key=lambda x: abs(float(x.get("duration") or 0) - duration))
        if abs(float(cands[0].get("duration") or 0) - duration) > 10:
            return None
    return cands[0]["syncedLyrics"]


def _fetch(title, artist, duration):
    """Senkron soz satirlarini dondurur; yoksa []. Ag hatasinda istisna firlatir."""
    if artist and duration and duration > 0:
        j = _http_get("/get", {"track_name": title, "artist_name": artist,
                               "duration": int(round(duration))})
        if isinstance(j, dict) and j.get("syncedLyrics"):
            return parse_lrc(j["syncedLyrics"])
    tries = []
    if artist:
        tries.append({"track_name": title, "artist_name": artist})
    tries.append({"q": (artist + " " + title).strip()})
    for params in tries:
        s = _pick(_http_get("/search", params), duration)
        if s:
            return parse_lrc(s)
    return []


def _worker(key, title, artist, duration):
    try:
        lines = _fetch(title, artist, duration)
        res = {"status": "ok" if lines else "none", "lines": lines, "err": False}
    except Exception as e:
        print("Soz arama hatasi:", type(e).__name__, e)
        res = {"status": "none", "lines": [], "err": True}
    res["ts"] = time.time()
    with _lock:
        _cache[key] = res


def lookup(title, artist="", duration=0.0):
    """Bu sarkinin sozlerini dondurur: (durum, satirlar). Ilk cagrida aramayi arka planda baslatir."""
    t, a = clean(title, artist)
    if not t:
        return "none", []
    key = (t.lower(), a.lower(), int(round(duration / 5.0)) if duration else 0)
    with _lock:
        ent = _cache.get(key)
        if ent is not None and ent.get("err") and time.time() - ent["ts"] > RETRY_AFTER:
            ent = None                      # ag hatasiydi: tekrar dene
        if ent is None:
            if len(_cache) >= MAX_CACHE:
                _cache.pop(next(iter(_cache)))
            _cache[key] = {"status": "loading", "lines": [], "ts": time.time(), "err": False}
            threading.Thread(target=_worker, args=(key, t, a, duration), daemon=True).start()
            return "loading", []
        return ent["status"], ent["lines"]
