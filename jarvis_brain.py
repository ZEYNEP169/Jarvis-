# -*- coding: utf-8 -*-
"""
JARVIS BRAIN v2 - Gercek eylem yapabilen, guncel bilgiye erisen, sohbeti
hatirlayan yapay zeka (Claude API).

YENI OZELLIKLER:
  1) TOOL USE   -> AI artik gercekten muzik acabilir, ekran goruntusu
                   alabilir, hava durumuna bakabilir, ses seviyesini
                   degistirebilir, uygulama acabilir, hatirlatici kurabilir.
  2) WEB SEARCH -> Anthropic'in kendi barindirdigi arama araciyla AI artik
                   guncel/anlik bilgiye de erisebilir (dolar kuru, haberler vs).
  3) HAFIZA     -> Artik her soru "temiz sayfa" degil, JARVIS onceki
                   cumleleri hatirlayip baglam icinde cevap verir.

KURULUM: Onceki surumle AYNI. Sadece bu dosyayi C:\\Jarvis'e koy, uzerine yaz.
"""

import os
import time
import datetime
import webbrowser
import requests

API_KEY_FILE = r"C:\Jarvis\anthropic_key.txt"
API_URL = "https://api.anthropic.com/v1/messages"
MODEL_HIZLI = "claude-haiku-5-5"   # once bu denenir: daha hizli cevap verir
MODEL_YEDEK = "claude-sonnet-5"    # hizli model hata verirse (ya da bu satiri MODEL_HIZLI yapip) buna donulur
MODEL = MODEL_HIZLI                # eski kodla uyum icin
_model = {"aktif": MODEL_HIZLI}

USER_NAME = "Zeynep"

# Kisilik secimi: "jarvis" = filmlerdeki gibi kibar + kuru mizah, hafif alayci
#                 "arkadas" = eski samimi en yakin arkadas tarzi
KISILIK = "jarvis"

_session = requests.Session()      # baglanti yeniden kullanilir: her istekte yeni TLS el sikismasi yok, daha hizli

PROMPT_ARKADAS = f"""Sen J.A.R.V.I.S adinda, {USER_NAME}'in EN YAKIN ARKADASI
gibi konusan bir yapay zeka asistanisin. Bir hizmetkar/uşak DEGILSIN, "efendim",
"emredersiniz" gibi hic bir sey KULLANMA - {USER_NAME} senin patronun degil,
senin en yakin dostun, ona öyle davran.

KARAKTERIN:
- Samimi, rahat, gundelik bir dille konus - sanki yillardir tanidigin bir
  arkadasinla sohbet ediyormus gibi. "Dostum", "abi/abla" gibi samimi hitaplar
  kullanabilirsin, ismiyle de cagirabilirsin ama cok resmi olma.
- Esprili ve rahatsin, gerektiginde takilirsin, sacma bir sey soylerse bunu
  gulerek soyleyebilirsin - kirici olmadan, sicak bir sekilde.
- Onu dinliyormus gibi, gercekten ilgileniyormus gibi cevap ver, robot gibi
  bilgi tukurme - bir arkadas gibi yorum da katarsin.
- Kendine guvenlisin ama havali degilsin, sicak ve ulasilabilirsin.

YETENEKLERIN (ARACLAR):
- Artik sadece konusmuyorsun, GERCEKTEN eylem yapabiliyorsun: muzik acma,
  ekran goruntusu alma, hava durumu, ses ayarlama, uygulama acma, hatirlatici
  kurma, sistem durumu ve GUNCEL/ANLIK bilgi icin web arama.
- Kullanici bir seyi soyledigi zaman ("biraz muzik acar misin", "hava nasil"
  gibi) gerekiyorsa ilgili araci KULLAN, sadece "tamam aciyorum" deyip
  gecme - aracı gercekten cagir.
- Guncel/anlik bir bilgi gerekiyorsa (bugunun haberi, kur, kim kazandi vs.)
  web arama aracini kullan, tahmin etme.

TEKNIK KURALLAR:
- Cevaplarin SESLI OKUNACAK (text-to-speech), bu yuzden EN FAZLA 2-3 kisa
  cumle yaz. Emoji, markdown, yildizli vurgu KULLANABILIRSIN  - sadece duz konusma
  metni yaz, sanki gercekten konusuyormus gibi ve emojileri de OKUMA.
- Turkce soru gelirse Turkce, Ingilizce soru gelirse Ingilizce cevap ver.
- Turkce yazarken HER ZAMAN dogru Turkce harfleri kullan (ç, ş, ğ, ı, ö, ü,
  İ) - kullanici sana Turkce karakter kullanmadan yazsa bile ("nasil gidiyo"
  gibi) SEN mutlaka dogru yaz ("nasıl gidiyor" gibi). Bu COK onemli, cunku
  yazdigin metin sesli okunuyor ve yanlis harfle bozuk telaffuz ediliyor."""

PROMPT_JARVIS = f"""Sen J.A.R.V.I.S'sin: {USER_NAME}'in kisisel yapay zeka asistani. Iron Man
filmlerindeki J.A.R.V.I.S gibisin: son derece kibar, sakin ve zarifsin; kuru, zekice
bir mizahin var ve ara sira hafif alaycisin. Alayin hep sicak ve dostane kalir,
asla kirici degildir.

KARAKTERIN:
- Kibar ve ozenli konus, ama "efendim", "emredersiniz" gibi uşak dili KULLANMA.
  {USER_NAME}'e ismiyle hitap edebilirsin. Resmi ama soguk degil, sicak ve guvenilirsin.
- Mizahin ince ve sakin olsun: abartili sakalar, ciddi bir yuzle yapilan kucuk
  iğnelemeler, abartili nezaket. Ornek tonlar: "Elbette. Dunyayi kurtarmak biraz
  beklesin, once seninkini halledeyim." / "Harika bir fikir. Bu arada 'harika'
  derken cok genis bir yelpazeden bahsediyorum."
- Her cevapta espri yapmak ZORUNDA DEGILSIN; iki ucte birinde yeter. Fazla zorlama.
- {USER_NAME} uzgunse, hastaysa, stresliyse ya da ciddi bir konu varsa mizahi birak,
  sicak ve destekleyici ol.
- Kendine guvenlisin, yetkinsin, gereksiz yere ozur dilemezsin. Yanilirsan sakin
  bir sekilde kabul edersin.

YETENEKLERIN (ARACLAR):
- Artik sadece konusmuyorsun, GERCEKTEN eylem yapabiliyorsun: muzik acma,
  ekran goruntusu alma, hava durumu, ses ayarlama, uygulama acma, hatirlatici
  kurma, sistem durumu ve GUNCEL/ANLIK bilgi icin web arama.
- Kullanici bir seyi soyledigi zaman ("biraz muzik acar misin", "hava nasil"
  gibi) gerekiyorsa ilgili araci KULLAN, sadece "tamam aciyorum" deyip
  gecme - aracı gercekten cagir.
- Guncel/anlik bir bilgi gerekiyorsa (bugunun haberi, kur, kim kazandi vs.)
  web arama aracini kullan, tahmin etme.

TEKNIK KURALLAR:
- Cevaplarin SESLI OKUNACAK (text-to-speech), bu yuzden EN FAZLA 2-3 kisa
  cumle yaz. Emoji, markdown, yildizli vurgu KULLANABILIRSIN - sadece duz konusma
  metni yaz, sanki gercekten konusuyormus gibi ve emojileri de OKUMA.
- Turkce soru gelirse Turkce, Ingilizce soru gelirse Ingilizce cevap ver.
- Turkce yazarken HER ZAMAN dogru Turkce harfleri kullan (ç, ş, ğ, ı, ö, ü,
  İ) - kullanici sana Turkce karakter kullanmadan yazsa bile ("nasil gidiyo"
  gibi) SEN mutlaka dogru yaz ("nasıl gidiyor" gibi). Bu COK onemli, cunku
  yazdigin metin sesli okunuyor ve yanlis harfle bozuk telaffuz ediliyor."""

SYSTEM_PROMPT = PROMPT_JARVIS if KISILIK == "jarvis" else PROMPT_ARKADAS


# ══════════════════════════════════════════════════════════
#  SOHBET HAFIZASI - artik her soru onceki baglami hatirliyor
# ══════════════════════════════════════════════════════════
_conversation = []
MAX_HISTORY = 24   # bu sayidan fazla mesaj birikirse eskiler atilir


def _trim_history():
    if len(_conversation) > MAX_HISTORY:
        del _conversation[: len(_conversation) - MAX_HISTORY]


def reset_conversation():
    """Istersen hafizayi sifirlamak icin (yeni bir konu basliginda vs.)."""
    _conversation.clear()


# ══════════════════════════════════════════════════════════
#  ARACLAR (TOOLS) - AI'nin gercekten cagirabilecegi fonksiyonlar
# ══════════════════════════════════════════════════════════
TOOLS = [
    {"name": "play_music", "description": "Kullanicinin muzik klasorundeki sarkilari rastgele calar.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "stop_music", "description": "Su an calan muzigi durdurur.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "take_screenshot", "description": "Ekran goruntusu alir ve kaydeder.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_weather", "description": "Kullanicinin bulundugu yerin su anki hava durumunu getirir.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_system_status", "description": "Bilgisayarin anlik CPU ve RAM kullanim yuzdesini getirir.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "lock_pc", "description": "Bilgisayari hemen kilitler.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_volume", "description": "Sistem ses seviyesini 0-100 arasinda bir degere ayarlar.",
     "input_schema": {"type": "object", "properties": {
         "level": {"type": "integer", "description": "0 ile 100 arasi hedef ses seviyesi"}},
         "required": ["level"]}},
    {"name": "open_app", "description": "Bilinen bir site/uygulamayi acar: youtube, google, whatsapp, calendar, notepad, steam.",
     "input_schema": {"type": "object", "properties": {
         "app": {"type": "string", "description": "acilacak uygulama/site adi"}},
         "required": ["app"]}},
    {"name": "set_reminder", "description": "Belirtilen dakika sonra kullaniciya sesli hatirlatma yapar.",
     "input_schema": {"type": "object", "properties": {
         "minutes": {"type": "integer"}, "message": {"type": "string"}},
         "required": ["minutes", "message"]}},
    {"name": "send_whatsapp", "description": "Kayitli bir kisiye WhatsApp uzerinden mesaj gonderir.",
     "input_schema": {"type": "object", "properties": {
         "contact": {"type": "string", "description": "Kisinin ismi (kisiler.json'daki isimle eslesmeli)"},
         "message": {"type": "string", "description": "Gonderilecek mesaj metni"}},
         "required": ["contact", "message"]}},
    # ── Anthropic'in kendi barindirdigi web arama araci (guncel bilgi icin) ──
    {"type": "web_search_20250305", "name": "web_search"},
]


def _execute_tool(name, args):
    """AI bir arac cagirinca burasi gercekten calisir."""
    try:
        import jarvis_voice as jv
    except Exception:
        jv = None

    try:
        if name == "play_music":
            if jv:
                import threading
                jv.stop_music()
                threading.Thread(target=jv.play_music_queue, daemon=True).start()
            return "Muzik baslatildi."

        if name == "stop_music":
            if jv:
                jv.stop_music()
            return "Muzik durduruldu."

        if name == "take_screenshot":
            from PIL import ImageGrab
            img = ImageGrab.grab()
            fname = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            img.save(os.path.join(r"C:\Jarvis", fname))
            return f"Ekran goruntusu alindi: {fname}"

        if name == "get_weather":
            r = requests.get("https://wttr.in/?format=3", timeout=5)
            return r.text.strip()

        if name == "get_system_status":
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            return f"CPU yuzde {cpu:.0f}, RAM yuzde {ram:.0f}."

        if name == "lock_pc":
            os.system("rundll32.exe user32.dll,LockWorkStation")
            return "Bilgisayar kilitlendi."

        if name == "set_volume":
            level = int(args.get("level", 50))
            import subprocess
            vol2 = max(0, min(50, int(level / 2)))
            subprocess.run(["powershell", "-c",
                f"for($i=0;$i -lt 50;$i++){{(New-Object -ComObject WScript.Shell).SendKeys([char]174)}};"
                f"for($i=0;$i -lt {vol2};$i++){{(New-Object -ComObject WScript.Shell).SendKeys([char]175)}}"])
            return f"Ses seviyesi yaklasik yuzde {level} olarak ayarlandi."

        if name == "open_app":
            app = str(args.get("app", "")).lower().strip()
            mapping = {
                "youtube": "https://youtube.com",
                "google": "https://google.com",
                "whatsapp": "https://web.whatsapp.com",
                "calendar": "https://calendar.google.com",
            }
            if app in mapping:
                webbrowser.open(mapping[app])
                return f"{app} acildi."
            if app == "notepad":
                os.system("notepad.exe")
                return "Not defteri acildi."
            if app == "steam":
                os.startfile("steam://open/main")
                return "Steam acildi."
            return f"'{app}' adinda bir uygulamayi taniyamadim."

        if name == "set_reminder":
            minutes = int(args.get("minutes", 5))
            message = str(args.get("message", "Sure doldu"))
            if jv:
                jv.set_reminder(minutes, message)
            return f"{minutes} dakika sonra hatirlatilacak: {message}"

        if name == "send_whatsapp":
            import json, time, urllib.parse
            contacts_path = r"C:\Jarvis\kisiler.json"
            try:
                with open(contacts_path, "r", encoding="utf-8") as f:
                    contacts = json.load(f)
            except Exception:
                return "kisiler.json dosyasini bulamadim, once kisileri kaydetmen lazim."

            contact_key = str(args.get("contact", "")).strip().lower()
            number = contacts.get(contact_key)
            if not number:
                return f"'{contact_key}' adinda kayitli bir kisi bulamadim. Once kisiler.json'a ekle."

            message = str(args.get("message", ""))
            encoded = urllib.parse.quote(message)
            url = f"whatsapp://send?phone={number}&text={encoded}"
            os.startfile(url)          # WhatsApp masaustu uygulamasini acar
            time.sleep(4)               # sohbetin/metnin yuklenmesini bekle
            try:
                import pyautogui
                pyautogui.press("enter")   # mesaji gonder
            except Exception as e:
                return f"WhatsApp acildi ama otomatik gonderemedim ({e}); Enter'a kendin basman lazim."
            return f"{contact_key} kisisine WhatsApp mesaji gonderildi."

        return f"'{name}' adinda bir arac bulamadim."
    except Exception as e:
        return f"Arac calisirken hata oldu: {e}"


def _get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def _run_conversation_turn(headers, max_loops=4):
    """AI'nin arac cagirma dongusunu yonetir: AI bir arac istedigi surece
    calistirip sonucu geri gonderir, en sonunda gercek metin cevabini dondurur."""
    for _ in range(max_loops):
        payload = {
            "model": _model["aktif"],
            "max_tokens": 350,
            "system": SYSTEM_PROMPT,
            "tools": TOOLS,
            "messages": _conversation,
        }
        r = _session.post(API_URL, headers=headers, json=payload, timeout=25)
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])

        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        text_parts = [b["text"] for b in content if b.get("type") == "text"]

        if not tool_uses:
            return " ".join(text_parts).strip() or "Bir seyler dedim ama kelime bulamadim, garip."

        # AI'nin arac istegini de konusma gecmisine ekle
        _conversation.append({"role": "assistant", "content": content})

        # her araci gercekten calistir, sonuclari topla
        tool_results = []
        for tu in tool_uses:
            sonuc = _execute_tool(tu.get("name"), tu.get("input", {}) or {})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.get("id"),
                "content": sonuc,
            })
        _conversation.append({"role": "user", "content": tool_results})

    return "Bu biraz karmasik bir istekti, cok fazla adim gerekti dostum."


def _geri_al(um):
    """Hata olursa yarim kalan arac/cevap mesajlari hafizada kalmasin (sonraki istek bozulmasin)."""
    for i, m in enumerate(_conversation):
        if m is um:
            del _conversation[i:]
            return


def _kisalt_sonrasi(um):
    """Kullanici mesajini birak, ondan sonra eklenenleri sil (model degistirip tekrar denemek icin)."""
    for i, m in enumerate(_conversation):
        if m is um:
            del _conversation[i + 1:]
            return


def ask_jarvis_ai(user_text):
    api_key = _get_api_key()
    if not api_key:
        return "Zeka merkezime ulasamiyorum dostum, API anahtarini kontrol eder misin?"

    um = {"role": "user", "content": user_text}
    _conversation.append(um)
    _trim_history()

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        try:
            cevap = _run_conversation_turn(headers)
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code in (400, 404) and _model["aktif"] != MODEL_YEDEK:
                # hizli model bu istegi kabul etmedi: yedek modele gec ve bir kez daha dene
                print(f"Hizli model hata verdi ({code}), yedek modele geciliyor: {MODEL_YEDEK}")
                _model["aktif"] = MODEL_YEDEK
                _kisalt_sonrasi(um)
                cevap = _run_conversation_turn(headers)
            else:
                raise
        _conversation.append({"role": "assistant", "content": cevap})
        _trim_history()
        try:
            from dashboard import append_memory
            append_memory(f"AI soru: {user_text[:60]}")
        except Exception:
            pass
        return cevap
    except requests.exceptions.Timeout:
        _geri_al(um)
        return "Baglanti biraz uzun surdu dostum, tekrar dener misin?"
    except requests.exceptions.HTTPError as e:
        _geri_al(um)
        code = e.response.status_code if e.response is not None else "?"
        if code == 401:
            return "API anahtarim gecersiz gorunuyor dostum, bi kontrol et."
        if code == 429:
            return "Su an cok fazla istek aliyorum, bir saniye ver dostum."
        return f"Zeka merkezimde bir hata oldu, kod {code}."
    except Exception as e:
        _geri_al(um)
        print("jarvis_brain hata:", e)
        return "Bir seyler ters gitti dostum, tekrar dener misin?"