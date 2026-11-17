import face_recognition
import cv2
import time
import os
import numpy as np

# Zeynep'in yüzünü yükle
zeynep_img = face_recognition.load_image_file(
    r"C:\Jarvis\faces\zeynep.jpeg"
)

zeynep_encodings = face_recognition.face_encodings(zeynep_img)

if not zeynep_encodings:
    raise ValueError("Zeynep'in fotoğrafında yüz bulunamadı.")

zeynep_encoding = zeynep_encodings[0]

known_encodings = [zeynep_encoding]
known_names = ["Zeynep"]


def start_face_recognition(speak_func):

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Kamera açılamadı!")
        return

    current_state = None
    last_seen_time = None          # Zeynep'in son goruldugu gercek zaman (time.time())
    GRACE_PERIOD = 15.0            # bu kadar SANIYE hic gorulmezse "gitti" say
    frame_counter = 0
    PROCESS_EVERY_N = 3            # performans icin her N karede bir isle

    while True:

        ret, frame = cap.read()

        if not ret:
            print("Kameradan görüntü alınamadı!")
            break

        frame_counter += 1
        if frame_counter % PROCESS_EVERY_N != 0:
            # bu kareyi atla, sadece pencereyi guncel tutmak icin devam et
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            continue

        # Daha az kucultme + daha fazla upsample = yan/egik yuzleri daha iyi yakalar
        small = cv2.resize(frame, (0, 0), fx=0.6, fy=0.6)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=2)
        encodings = face_recognition.face_encodings(rgb, locations)

        frame_has_zeynep = False
        frame_has_unknown = False

        for encoding in encodings:
            matches = face_recognition.compare_faces(known_encodings, encoding, tolerance=0.6)
            if True in matches:
                frame_has_zeynep = True
            else:
                frame_has_unknown = True

        now = time.time()

        if frame_has_zeynep:
            last_seen_time = now
            if current_state != "Zeynep":
                current_state = "Zeynep"
                speak_func("Welcome back Zeynep. All systems online.")

        elif frame_has_unknown:
            if current_state != "Unknown":
                current_state = "Unknown"
                speak_func("Warning. Unauthorized person detected.")

        else:
            # bu karede hic yuz yok (bakis acisi/isik/gecici kayip olabilir)
            if current_state == "Zeynep" and last_seen_time is not None:
                if now - last_seen_time >= GRACE_PERIOD:
                    current_state = None
                    last_seen_time = None
                    speak_func("Goodbye Zeynep. See you soon.")

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":

    from jarvis_voice import speak

    start_face_recognition(speak)