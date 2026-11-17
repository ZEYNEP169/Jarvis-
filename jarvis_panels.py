# -*- coding: utf-8 -*-
"""
JARVIS PANELLERI: gorevler ve notlar
====================================
Veri katmani + Turkce sesli komutlar. Adadaki (jarvis_island.py) panel bu dosyadan
veri okur; adadaki yazma satiri da add_task / add_note fonksiyonlarini kullanir.

Pano gecmisi sadece BELLEKTE tutulur (diske yazilmaz, JARVIS kapaninca silinir).

Dosyalar (C:\\Jarvis icinde):
  tasks.json   -> [{"text": "...", "done": false}, ...]
  notes.json   -> [{"t": "2026-11-05 21:44", "text": "..."}, ...]

Sesli komut ornekleri:
  gorev ekle matematik calis   | gorevlerim | 2. gorevi bitir | 2. gorevi sil
  tamamlananlari temizle
  not al yarin kutuphaneden kitap al | notlarim | son notu sil
"""

import os
import re
import json
import threading
import datetime

DATA_DIR = r"C:\Jarvis" if os.name == "nt" else os.path.expanduser("~/.jarvis")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    pass

MAX_ROWS = 6                      # adada ayni anda gorunen en fazla satir
_lock = threading.RLock()


# ══════════════════════════════════════════
#  Yardimcilar
# ══════════════════════════════════════════
def cap(s):
    """Ilk harfi buyutur (i -> İ, ı -> I)."""
    s = s.strip()
    if not s:
        return s
    f = s[0]
    f = "İ" if f == "i" else ("I" if f == "ı" else f.upper())
    return f + s[1:]


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print("Kaydetme hatasi:", path, e)


# ══════════════════════════════════════════
#  GOREVLER
# ══════════════════════════════════════════
def _tasks():
    return [x for x in _load(TASKS_FILE) if isinstance(x, dict) and x.get("text")]


def _save_tasks(items):
    items.sort(key=lambda x: bool(x.get("done")))   # yapilanlar alta (kararli siralama)
    _save(TASKS_FILE, items[-100:])


def add_task(text):
    with _lock:
        items = _tasks()
        items.append({"text": text, "done": False})
        _save_tasks(items)


def toggle_task(i):
    """i. gorevi (0'dan) yapildi/yapilmadi yapar. (metin, yeni_durum) ya da None doner."""
    with _lock:
        items = _tasks()
        if not (0 <= i < len(items)):
            return None
        items[i]["done"] = not items[i].get("done")
        res = (items[i]["text"], items[i]["done"])
        _save_tasks(items)
        return res


def remove_task(i):
    with _lock:
        items = _tasks()
        if not (0 <= i < len(items)):
            return None
        text = items.pop(i)["text"]
        _save_tasks(items)
        return text


def clear_done():
    with _lock:
        items = _tasks()
        kalan = [x for x in items if not x.get("done")]
        _save_tasks(kalan)
        return len(items) - len(kalan)


# ══════════════════════════════════════════
#  NOTLAR
# ══════════════════════════════════════════
def _notes():
    return [x for x in _load(NOTES_FILE) if isinstance(x, dict) and x.get("text")]


def add_note(text):
    with _lock:
        items = _notes()
        items.append({"t": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "text": text})
        _save(NOTES_FILE, items[-200:])


def delete_last_note():
    with _lock:
        items = _notes()
        if not items:
            return None
        text = items.pop()["text"]
        _save(NOTES_FILE, items)
        return text


# ══════════════════════════════════════════
#  PANO GECMISI (sadece bellekte; sifre vb. diske yazilmasin diye)
# ══════════════════════════════════════════
CLIP_MAX = 20
CLIP_MAX_CHARS = 2000         # bundan uzun kopyalar (buyuk metin / kod) kaydedilmez
_clips = []


def clip_add(text):
    """Yeni kopyalanan metni listenin basina koyar. Ayni metin varsa one tasir."""
    text = (text or "").strip()
    if not text or len(text) > CLIP_MAX_CHARS:
        return False
    with _lock:
        if text in _clips:
            _clips.remove(text)
        _clips.insert(0, text)
        del _clips[CLIP_MAX:]
    return True


def clip_get(i):
    with _lock:
        return _clips[i] if 0 <= i < len(_clips) else None


def clip_remove(i):
    with _lock:
        if 0 <= i < len(_clips):
            return _clips.pop(i)
    return None


def clip_clear():
    with _lock:
        n = len(_clips)
        _clips.clear()
    return n


def _clip_line(text):
    return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════
#  Adanin okudugu fonksiyonlar
# ══════════════════════════════════════════
def rows_for(tab):
    """-> (satirlar, fazladan_kac, bos_mesaj). Her satir: lead, text, done, dim"""
    if tab == "tasks":
        rows = [{"lead": str(i + 1), "text": x["text"], "done": bool(x.get("done")), "dim": False}
                for i, x in enumerate(_tasks())]
        empty = "Görev yok  ·  aşağıya yaz ya da \"görev ekle ...\" de"
    elif tab == "clips":
        with _lock:
            snap = list(_clips)
        rows = [{"lead": str(i + 1), "text": _clip_line(t), "done": False, "dim": False}
                for i, t in enumerate(snap)]
        empty = "Pano boş  ·  bir şey kopyala, burada görünür"
    else:
        today = datetime.date.today()
        rows = []
        for x in reversed(_notes()):
            try:
                t = datetime.datetime.strptime(x.get("t", ""), "%Y-%m-%d %H:%M")
                lead = f"{t:%H:%M}" if t.date() == today else f"{t.day:02d}/{t.month:02d}"
            except Exception:
                lead = "•"
            rows.append({"lead": lead, "text": x["text"], "done": False, "dim": False})
        empty = "Not yok  ·  aşağıya yaz ya da \"not al ...\" de"
    return rows[:MAX_ROWS], max(0, len(rows) - MAX_ROWS), empty


def counts():
    return {"tasks": sum(1 for x in _tasks() if not x.get("done")),
            "notes": len(_notes()),
            "clips": len(_clips)}


# ══════════════════════════════════════════
#  Sesli komutlar
# ══════════════════════════════════════════
def _goster(tab):
    try:
        import jarvis_island
        jarvis_island.show_panel(tab)
    except Exception:
        pass


def _sayi(k):
    m = re.search(r"\d+", k)
    if m:
        return int(m.group())
    for w, n in (("ilk", 1), ("birinci", 1), ("ikinci", 2), ("ucuncu", 3),
                 ("dorduncu", 4), ("besinci", 5), ("altinci", 6)):
        if re.search(r"\b" + w + r"\b", k):
            return n
    return None


def handle(komut, orijinal, speak):
    """komut: normalize (ASCII) metin, orijinal: Turkce harfli ayni uzunluktaki metin.
    Komutu isledi ise True doner; baska komutlara birakmak icin False."""
    k = komut

    # ── GOREV ekle ──
    m = re.search(r"\b(?:yeni gorev|gorev ekle|gorev yaz)\b[:,]?\s*", k)
    if m:
        metin = orijinal[m.end():].strip(" .,:;")
        if not metin:
            speak("Hangi görevi ekleyeyim?")
            return True
        metin = cap(metin)
        add_task(metin)
        speak(f"Görev eklendi: {metin}")
        _goster("tasks")
        return True

    # ── GOREV bitir / geri al ──
    if re.search(r"\bgorev", k) and re.search(r"\b(?:bitir|tamamla|yaptim|bitti|tamamlandi)\w*", k):
        n = _sayi(k)
        if n is None:
            speak("Kaçıncı görevi bitireyim? Örneğin: 2. görevi bitir.")
            return True
        r = toggle_task(n - 1)
        if r is None:
            speak(f"{n} numaralı bir görev yok.")
        else:
            speak(f"Tamamlandı: {r[0]}" if r[1] else f"Geri alındı: {r[0]}")
        _goster("tasks")
        return True

    # ── GOREV sil ──
    if re.search(r"\bgorev", k) and re.search(r"\bsil\w*", k):
        n = _sayi(k)
        if n is None:
            speak("Kaçıncı görevi sileyim? Örneğin: 2. görevi sil.")
            return True
        t = remove_task(n - 1)
        speak(f"Silindi: {t}" if t else f"{n} numaralı bir görev yok.")
        _goster("tasks")
        return True

    # ── tamamlananlari temizle ──
    if re.search(r"\b(?:tamamlanan|biten|yapilan)\w*", k) and re.search(r"\b(?:temizle|sil)\w*", k):
        c = clear_done()
        speak(f"{c} tamamlanan görev temizlendi." if c else "Temizlenecek görev yok.")
        _goster("tasks")
        return True

    # ── GOREV listesi ──
    if re.search(r"\bgorev(?:lerim|leri|ler| listesi)\b|\byapilacaklar\b", k):
        bekleyen = [x["text"] for x in _tasks() if not x.get("done")]
        if not bekleyen:
            speak("Bekleyen görevin yok.")
        else:
            ilk = ". ".join(f"{i + 1}. {t}" for i, t in enumerate(bekleyen[:3]))
            speak(f"{len(bekleyen)} bekleyen görevin var. {ilk}")
        _goster("tasks")
        return True

    # ── NOT al ──
    m = re.search(r"\bnot (?:al|ekle|yaz)\b[:,]?\s*", k)
    if m:
        metin = orijinal[m.end():].strip(" .,:;")
        if not metin:
            speak("Ne not alayım?")
            return True
        add_note(cap(metin))
        speak("Not alındı.")
        _goster("notes")
        return True

    if re.search(r"\bson not(?:u)? sil", k):
        t = delete_last_note()
        speak(f"Son not silindi: {t}" if t else "Silinecek not yok.")
        _goster("notes")
        return True

    if re.search(r"\bnotlarim\w*|\bnotlari (?:goster|oku)\b|\bnotlar\b", k):
        son = [x["text"] for x in reversed(_notes())][:3]
        speak("Son notların: " + ". ".join(son) if son else "Hiç notun yok.")
        _goster("notes")
        return True

    # ── PANO ──
    if re.search(r"\bpano\w*", k):
        if re.search(r"\b(?:temizle|sil|bosalt)\w*", k):
            n = clip_clear()
            speak("Pano geçmişi temizlendi." if n else "Pano geçmişi zaten boş.")
        else:
            speak(f"Pano geçmişinde {len(_clips)} kayıt var." if _clips else "Pano geçmişi boş.")
        _goster("clips")
        return True

    return False