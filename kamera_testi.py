# -*- coding: utf-8 -*-
"""
JARVIS - Kamera ve el hareketi test programi
Calistirma:
    cd C:\Jarvis
    python kamera_testi.py

Cikmak icin kamera penceresinde Q veya ESC tusuna basin.
"""

import os
import sys
import time
import math
import urllib.request

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
DATA_DIR = r"C:\Jarvis" if os.name == "nt" else os.path.expanduser("~/.jarvis")
MODEL_PATH = os.path.join(DATA_DIR, "hand_landmarker.task")

TIPS = (8, 12, 16, 20)
PIPS = (6, 10, 14, 18)


def get_model():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        print("[OK] El modeli bulundu:", MODEL_PATH)
        return

    print("[..] El modeli indiriliyor (internet gerekir)...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except Exception as exc:
        raise RuntimeError(
            "Model indirilemedi. Internet baglantisini kontrol edin.\n"
            f"Adres: {MODEL_URL}\nHata: {exc}"
        )
    if os.path.getsize(MODEL_PATH) < 1_000_000:
        raise RuntimeError("Indirilen model dosyasi gecersiz veya eksik.")
    print("[OK] Model indirildi:", MODEL_PATH)


def distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def classify(hand):
    wrist = hand[0]
    extended = 0
    folded = 0

    for tip, pip in zip(TIPS, PIPS):
        base_distance = distance(hand[pip], wrist)
        if base_distance < 1e-6:
            return "EL ALGILANDI"
        ratio = distance(hand[tip], wrist) / base_distance
        if ratio >= 1.20:
            extended += 1
        elif ratio <= 1.00:
            folded += 1

    if extended == 4:
        return "ACIK AVUC"
    if extended == 0 and folded >= 3:
        return "YUMRUK"
    return "EL ALGILANDI"


def main():
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except Exception as exc:
        print("[HATA] Kutuphane yuklenemedi:", exc)
        print("Terminalde su komutu calistirin:")
        print("python -m pip install mediapipe opencv-python")
        return

    print("[OK] OpenCV ve MediaPipe yuklendi.")
    get_model()

    print("[..] Kamera aciliyor...")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(0)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError(
            "Kamera acilamadi. Windows Ayarlar > Gizlilik ve guvenlik > Kamera "
            "bolumunden masaustu uygulamalarina kamera izni verin. "
            "Kamerayi kullanan diger uygulamalari da kapatin."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.55,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    landmarker = vision.HandLandmarker.create_from_options(options)
    print("[OK] Kamera ve el modeli hazir.")
    print("Elinizi kameraya gosterin. Cikmak icin Q veya ESC.")

    last_timestamp = 0
    last_print = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[HATA] Kameradan goruntu okunamadi.")
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            timestamp = max(last_timestamp + 1, int(time.monotonic() * 1000))
            last_timestamp = timestamp

            result = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                timestamp,
            )

            label = "EL YOK"

            if result.hand_landmarks:
                hand = result.hand_landmarks[0]
                label = classify(hand)

                height, width = frame.shape[:2]
                for point in hand:
                    x = int(point.x * width)
                    y = int(point.y * height)
                    cv2.circle(frame, (x, y), 4, (0, 255, 255), -1)

                # Parmak ve avuc baglantilarini ciz
                connections = vision.HandLandmarksConnections.HAND_CONNECTIONS
                for connection in connections:
                    start = hand[connection.start]
                    end = hand[connection.end]
                    p1 = (int(start.x * width), int(start.y * height))
                    p2 = (int(end.x * width), int(end.y * height))
                    cv2.line(frame, p1, p2, (255, 180, 0), 2)

            cv2.rectangle(frame, (10, 10), (330, 65), (20, 20, 20), -1)
            cv2.putText(frame, label, (22, 48),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            cv2.putText(frame, "Q / ESC: Cikis", (10, 455),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            cv2.imshow("JARVIS - El Hareketi Testi", frame)

            now = time.time()
            if now - last_print >= 1.0:
                print("Durum:", label)
                last_print = now

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

    finally:
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
        print("[OK] Kamera kapatildi.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\n[HATA]", exc)
        input("\nKapatmak icin Enter'a basin...")
