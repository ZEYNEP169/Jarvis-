# J.A.R.V.I.S.

🇹🇷 [Türkçe](#-türkçe) · 🇬🇧 [English](#-english) · 🇫🇷 [Français](#-français)

---

## 🇹🇷 Türkçe

Windows için sesle çalışan, Iron Man'in J.A.R.V.I.S.'inden esinlenmiş kişisel yapay zeka asistanı. Python ve PyQt5 ile yazıldı. Programlamayı öğrenmek için yaptığım bir hobi projesi, geliştirilmeye devam ediyor.

### Özellikler

- 🎙️ **Sesli komut ve sohbet:** Türkçe konuşma tanıma, edge-tts ile doğal ses, Claude (Anthropic API) ile yapay zeka cevapları
- 🏝️ **Dynamic Island:** ekranın üstünde ses dalgası, cevaplar, telefon bildirimleri, müzik kontrolü ve maskot
- ✋ **El hareketleri (MediaPipe):** müzik kontrolü, havada fare, iki elle parlaklık
- 🌍 **3B hologram dünya:** iki el hareketiyle açılan dönen küre; gece/gündüz, şehir saatleri, hava durumu
- 🎯 **Hedef kilidi:** "ekranı tara" dediğinde ekrandaki şeyleri bulur ve Iron Man tarzı çerçeveler çizer
- 🚀 **Açılış animasyonu:** arc reactor temalı
- 📱 **Telefon bağlantısı:** ntfy ile bildirimler, ngrok ile PIN korumalı web arayüzü

### Gizlilik ve güvenlik

- **"Ekranı tara"** komutu ekran görüntüsünü yapay zeka için Anthropic API'sine gönderir. Hassas bilgi açıkken kullanma.
- Web arayüzünü internete açarsan güçlü bir PIN kullan.
- Anahtarlarını, PIN'ini ve ntfy konu adını asla paylaşma.

---

## 🇬🇧 English

A voice-controlled personal AI assistant for Windows, inspired by Iron Man's J.A.R.V.I.S. Built with Python and PyQt5. It is a hobby project I made to learn programming, and it is still a work in progress.

### Features

- 🎙️ **Voice commands and chat:** Turkish speech recognition, natural voice with edge-tts, AI answers from Claude (Anthropic API)
- 🏝️ **Dynamic Island:** a bar at the top of the screen with a voice waveform, replies, phone notifications, music controls and a mascot
- ✋ **Hand gestures (MediaPipe):** music control, an air mouse, two-hand brightness control
- 🌍 **3D hologram Earth:** a rotating globe opened with a two-hand gesture; day/night, city clocks, weather
- 🎯 **Target lock:** say "scan the screen" and it finds things on screen and draws Iron Man style frames
- 🚀 **Boot animation:** arc reactor theme
- 📱 **Phone link:** notifications through ntfy, PIN-protected web interface through ngrok

### Privacy and security

- The **"scan the screen"** command sends a screenshot to the Anthropic API for the AI to analyze. Do not use it while sensitive information is on screen.
- If you expose the web interface to the internet, use a strong PIN.
- Never share your API keys, PIN or ntfy topic name.

---

## 🇫🇷 Français

Assistant personnel d'intelligence artificielle à commande vocale pour Windows, inspiré du J.A.R.V.I.S. d'Iron Man. Développé avec Python et PyQt5. C'est un projet de loisir créé pour apprendre la programmation, et il continue d'évoluer.

### Fonctionnalités

- 🎙️ **Commandes vocales et discussion :** reconnaissance vocale en turc, voix naturelle avec edge-tts, réponses de l'IA via Claude (API Anthropic)
- 🏝️ **Dynamic Island :** une barre en haut de l'écran avec onde sonore, réponses, notifications du téléphone, contrôle de la musique et mascotte
- ✋ **Gestes de la main (MediaPipe) :** contrôle de la musique, souris dans les airs, luminosité à deux mains
- 🌍 **Terre holographique 3D :** un globe en rotation ouvert par un geste à deux mains ; jour/nuit, heure des villes, météo
- 🎯 **Verrouillage de cible :** dites « scanne l'écran » et il repère les éléments à l'écran et dessine des cadres façon Iron Man
- 🚀 **Animation de démarrage :** thème réacteur Arc
- 📱 **Lien avec le téléphone :** notifications via ntfy, interface web protégée par code PIN via ngrok

### Confidentialité et sécurité

- La commande **« scanne l'écran »** envoie une capture d'écran à l'API Anthropic pour analyse. Ne l'utilisez pas lorsque des informations sensibles sont affichées.
- Si vous exposez l'interface web sur Internet, utilisez un code PIN robuste.
- Ne partagez jamais vos clés d'API, votre PIN ni le nom de votre sujet ntfy.

---

## Setup / Kurulum / Installation

Windows, Python 3.11

```bash
git clone https://github.com/ZEYNEP169/jarvis.git
cd jarvis
pip install PyQt5 requests psutil numpy pillow opencv-python mediapipe edge-tts gTTS python-vlc SpeechRecognition pyaudio flask flask-socketio mss qrcode ngrok winsdk wmi pyautogui screen-brightness-control
python jarvis_voice.py
```

🇹🇷 Bazı paketler (ör. `pyaudio`, VLC) ayrıca kurulum gerektirebilir. Eksik paket hatası alırsan adını `pip install` ile kur.
🇬🇧 Some packages (e.g. `pyaudio`, VLC) may need separate installation. If you get a missing-package error, install it with `pip install`.
🇫🇷 Certains paquets (p. ex. `pyaudio`, VLC) peuvent nécessiter une installation séparée. En cas d'erreur de paquet manquant, installez-le avec `pip install`.

### 🔐 Secrets (do NOT put in code / koda YAZMA / ne PAS mettre dans le code)

| What / Ne / Quoi | Environment variable | Or file / Ya da dosya / Ou fichier |
|---|---|---|
| Anthropic API key | `ANTHROPIC_API_KEY` | `anthropic_key.txt` |
| Web PIN | `JARVIS_PIN` | `jarvis_pin.txt` (auto-created) |
| ngrok token | `NGROK_AUTHTOKEN` | — |
| ngrok domain | `JARVIS_NGROK_DOMAIN` | `ngrok_domain.txt` |
| ntfy topic | `JARVIS_NTFY_TOPIC` | `ntfy_topic.txt` |
| Phone listener topic | `JARVIS_PHONE_TOPIC` | `phone_topic.txt` |

🇹🇷 Bu dosyalar `.gitignore` ile GitHub'a yüklenmez. · 🇬🇧 These files are excluded from GitHub by `.gitignore`. · 🇫🇷 Ces fichiers sont exclus de GitHub par `.gitignore`.

## Built with / Teknolojiler / Technologies

Python · PyQt5 · MediaPipe · OpenCV · edge-tts · Claude API · Flask-SocketIO · ngrok · ntfy · Open-Meteo · Natural Earth (public domain)

## License / Lisans / Licence

MIT — see / bkz. / voir [LICENSE](LICENSE)
