# -*- coding: utf-8 -*-
"""
SES TESTİ - Edge TTS neden yavaş, hangi ses hızlı?
Kullanım (JARVIS KAPALIYKEN):   cd C:\\Jarvis   ve   python ses_testi.py
JARVIS'e dokunmaz, sadece ölçüm yapar. Yaklaşık 1-2 dakika sürer.
"""
import asyncio
import os
import socket
import tempfile
import time

import edge_tts

CUMLE = "Merhaba dostum, bugün nasılsın, seni görmek güzel."

# (ses, Türkçeyi iyi okur mu?)
SESLER = [
    ("en-US-AvaMultilingualNeural", True),       # şu an kullandığın
    ("en-US-AndrewMultilingualNeural", True),
    ("en-US-BrianMultilingualNeural", True),
    ("tr-TR-EmelNeural", True),
    ("tr-TR-AhmetNeural", True),
    ("en-US-AriaNeural", False),                 # sadece hız karşılaştırması için
]


def ag_testi():
    print("\n== 1) AĞ TESTİ (speech.platform.bing.com) ==")
    host = "speech.platform.bing.com"
    t = time.time()
    try:
        bilgiler = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except Exception as e:
        print("DNS hatası:", e)
        return
    print(f"DNS çözme: {time.time() - t:.2f} sn")
    gorulen = set()
    for fam, _, _, _, addr in bilgiler:
        ad = "IPv6" if fam == socket.AF_INET6 else "IPv4"
        if ad in gorulen:
            continue
        gorulen.add(ad)
        t = time.time()
        try:
            s = socket.create_connection((addr[0], addr[1]), timeout=8)
            s.close()
            print(f"TCP bağlantısı {ad}: {time.time() - t:.2f} sn")
        except Exception as e:
            print(f"TCP bağlantısı {ad}: BAŞARISIZ ({type(e).__name__}) {time.time() - t:.1f} sn")


async def _uret(ses, yol):
    c = edge_tts.Communicate(CUMLE, voice=ses)
    await asyncio.wait_for(c.save(yol), timeout=40)


def sesi_dene(ses):
    sureler = []
    for _ in range(2):
        yol = os.path.join(tempfile.gettempdir(), "ses_testi.mp3")
        t = time.time()
        try:
            asyncio.run(_uret(ses, yol))
            sureler.append(time.time() - t)
        except Exception as e:
            print(f"  {ses}: HATA {type(e).__name__} {getattr(e, 'status', '')} ({time.time() - t:.1f} sn)")
            return None
    print(f"  {ses}: 1. deneme {sureler[0]:.1f} sn, 2. deneme {sureler[1]:.1f} sn")
    return sum(sureler) / 2


def main():
    print("edge-tts surumu:", getattr(edge_tts, "__version__", "?"))
    ag_testi()
    print("\n== 2) SES TESTİ (aynı cümle, her ses 2 kez) ==")
    sonuc = {}
    for ses, turkce_ok in SESLER:
        ort = sesi_dene(ses)
        if ort is not None:
            sonuc[ses] = (ort, turkce_ok)

    print("\n== SONUÇ ==")
    if not sonuc:
        print("Hiçbir ses çalışmadı. İnternet/güvenlik duvarı sorunu olabilir (VPN, antivirüs, ağ).")
        return
    hepsi = sorted(sonuc.items(), key=lambda x: x[1][0])
    en_hizli = hepsi[0][1][0]
    en_yavas = hepsi[-1][1][0]
    if en_hizli > 6:
        print("Tüm sesler yavaş (en hızlısı bile %.1f sn). Sorun ses değil, AĞ yolu." % en_hizli)
        print("Dene: telefonun hotspot'una bağlanıp bu testi tekrar çalıştır;")
        print("hızlanıyorsa internetin/modemin Microsoft'a giden yolu yavaş demektir.")
        print("VPN ya da antivirüsün 'web koruması' açıksa kapatıp tekrar dene.")
        return
    uygun = [(s, v[0]) for s, v in hepsi if v[1]]
    if uygun:
        ses, sure = uygun[0]
        print(f"Türkçeyi iyi okuyan en hızlı ses: {ses} ({sure:.1f} sn)")
        print("jarvis_voice.py içinde şu satırı bununla değiştir:")
        print(f'VARSAYILAN_SES = "{ses}"')
    if en_yavas - en_hizli > 4:
        print("(Sesler arasında belirgin fark var: sorun ağdan çok seçilen ses.)")


if __name__ == "__main__":
    main()
