# -*- coding: utf-8 -*-
"""
PHONE LISTENER - Telefondan gelen bildirimleri dinler, JARVIS sesli söyler.

NASIL ÇALIŞIR (kısaca):
  1) Telefon (MacroDroid ile) ntfy.sh'ta belirli bir "konu"ya mesaj yollar.
  2) Bu dosya aynı konuyu internetten dinler (ntfy "akış" modu: bağlantı açık
     kalır, yeni mesaj gelince satır satır bize iletir).
  3) Mesaj gelince JARVIS sesli söyler.

GÜVENLİK KURALI (önemli):
  Telefondan gelen yazı ASLA komut olarak çalıştırılmaz, sadece okunur.
  Konu adını bilen biri sahte mesaj atabilir. Eğer mesajlar komut olsaydı
  (ör. "bilgisayarı kapat"), o kişi bilgisayarını kontrol edebilirdi.

KURULUM:
  C:\\Jarvis\\phone_topic.txt dosyasına SADECE konu adını yaz (uzun ve rastgele).
  Konu adı üretmek için terminalde:
    python -c "import secrets; print('jarvis_phone_' + secrets.token_urlsafe(16))"
"""

import os
import json
import time
import threading
import requests

TOPIC_FILE = r"C:\Jarvis\phone_topic.txt"
MAX_SPOKEN_CHARS = 200   # çok uzun mesajlar kesilsin


def _load_topic():
    topic = os.environ.get("JARVIS_PHONE_TOPIC", "").strip()
    if topic:
        return topic
    try:
        with open(TOPIC_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def parse_line(line):
    """ntfy'nin gönderdiği tek bir JSON satırını okur.
    Gerçek bir mesajsa (zaman, metin) döndürür; keepalive/open gibi
    olaylarda None döndürür."""
    try:
        data = json.loads(line)
    except Exception:
        return None
    if data.get("event") != "message":
        return None
    text = str(data.get("message", "")).strip()
    if not text:
        return None
    return int(data.get("time", time.time())), text[:MAX_SPOKEN_CHARS]


def _announce(text):
    """Mesajı JARVIS'e sesli söylettir. Hata olursa program çökmesin."""
    try:
        import jarvis_voice
        if jarvis_voice.normalize(text).strip() == "sabah ozeti":
            jarvis_voice.sabah_ozeti()
        else:
            jarvis_voice.speak(text)
    except Exception as e:
        print("Telefon bildirimi seslendirilemedi:", e)
    try:
        import jarvis_island
        jarvis_island.mark_phone(text)
    except Exception:
        pass

def _listen_loop(topic):
    since = int(time.time())          # sadece bundan SONRAKİ mesajları al
    wait = 2
    while True:
        try:
            url = f"https://ntfy.sh/{topic}/json?since={since}"
            # ntfy 30 sn'de bir "keepalive" yollar; 90 sn sessizlik = bağlantı bozuk
            with requests.get(url, stream=True, timeout=(10, 90)) as r:
                r.raise_for_status()
                wait = 2              # bağlandık, bekleme süresini sıfırla
                print("Telefon dinleyicisi bağlandı.")
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    parsed = parse_line(raw.decode("utf-8", errors="ignore"))
                    if parsed:
                        msg_time, text = parsed
                        since = msg_time + 1   # aynı mesajı tekrar almayalım
                        print("Telefondan mesaj:", text)
                        _announce(text)
        except Exception as e:
            print(f"Telefon dinleyicisi koptu ({e}), {wait} sn sonra tekrar denenecek.")
        time.sleep(wait)
        wait = min(wait * 2, 60)      # 2, 4, 8 ... en fazla 60 sn bekle


def start_phone_listener():
    topic = _load_topic()
    if not topic:
        print("Telefon dinleyicisi kapalı: phone_topic.txt bulunamadı veya boş.")
        return None
    t = threading.Thread(target=_listen_loop, args=(topic,), daemon=True)
    t.start()
    return t
