
import time
import cv2
import requests
from fast_alpr import ALPR

API_URL = "http://127.0.0.1:5000/api/authorize"
CAMERA_STATUS_URL = "http://127.0.0.1:5000/api/camera-status"

CAMERA_INDEX = 0
INFERENCE_EVERY_N_FRAMES = 5
REQUEST_COOLDOWN_SECONDS = 5
MIN_DETECTION_CONFIDENCE = 0.60


def publish_camera_status(plate, confidence, auth_data):
    """Publish the recognition result for the Raspberry Pi."""
    payload = {
        "plate": plate,
        "approved": auth_data.get("approved") is True,
        "reason": auth_data.get("reason", "unknown"),
        "detection_confidence": confidence,
    }

    try:
        response = requests.post(
            CAMERA_STATUS_URL,
            json=payload,
            timeout=3,
        )
        response.raise_for_status()
        print("Camera status published:", response.json())
        return True

    except requests.RequestException as exc:
        print("Could not publish camera status:", exc)
        return False


def main():
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        print("ERROR: Could not open webcam.")
        print("Close other apps using the camera and check Windows camera permissions.")
        return

    try:
        alpr = ALPR()
    except Exception as exc:
        camera.release()
        print("ERROR: Could not initialize Fast-ALPR.")
        print(exc)
        return

    print("Webcam + HSRP authorization started.")
    print("Authorization API:", API_URL)
    print("Camera status API:", CAMERA_STATUS_URL)
    print("Press Q in the webcam window to quit.")
    print("Gate movement is disabled.")

    frame_count = 0
    last_request_time = 0.0
    last_plate_sent = ""
    display_plate = ""
    display_result = "Show a number plate"
    display_color = (255, 255, 255)
    last_box = None

    try:
        while True:
            ret, frame = camera.read()

            if not ret:
                print("ERROR: Could not read a webcam frame.")
                break

            frame_count += 1

            if frame_count % INFERENCE_EVERY_N_FRAMES == 0:
                try:
                    detections = alpr.predict(frame)

                    if detections:
                        result = max(
                            detections,
                            key=lambda item: item.detection.confidence,
                        )

                        confidence = float(result.detection.confidence)
                        box = result.detection.bounding_box

                        last_box = (
                            int(box.x1), int(box.y1),
                            int(box.x2), int(box.y2),
                        )

                        display_plate = str(result.ocr.text).strip().upper()

                        now = time.time()
                        should_send = (
                            display_plate
                            and confidence >= MIN_DETECTION_CONFIDENCE
                            and (
                                display_plate != last_plate_sent
                                or now - last_request_time
                                >= REQUEST_COOLDOWN_SECONDS
                            )
                        )

                        if confidence < MIN_DETECTION_CONFIDENCE:
                            display_result = (
                                f"Low detection confidence: {confidence:.2f}"
                            )
                            display_color = (0, 165, 255)

                        elif should_send:
                            try:
                                response = requests.post(
                                    API_URL,
                                    json={"plate": display_plate},
                                    timeout=3,
                                )
                                last_request_time = time.time()
                                last_plate_sent = display_plate

                                try:
                                    data = response.json()
                                except ValueError:
                                    data = {
                                        "approved": False,
                                        "reason": "invalid_server_response",
                                    }

                                if response.ok:
                                    publish_camera_status(
                                        display_plate,
                                        confidence,
                                        data,
                                    )
                                else:
                                    print(
                                        "Authorization API HTTP error:",
                                        response.status_code,
                                        data,
                                    )

                                approved = (
                                    response.ok
                                    and data.get("approved") is True
                                )
                                owner = str(data.get("owner_name") or "")
                                reason = str(data.get("reason", "unknown"))
                                slots = data.get("available_slots")

                                if approved:
                                    display_result = (
                                        f"APPROVED - {owner} | Slots: {slots}"
                                    )
                                    display_color = (0, 200, 0)
                                else:
                                    display_result = f"DENIED - {reason}"
                                    display_color = (0, 0, 255)

                                print(
                                    f"Plate: {display_plate} | "
                                    f"Detection confidence: {confidence:.3f} | "
                                    f"HTTP: {response.status_code} | "
                                    f"Authorization: {data}"
                                )

                            except requests.RequestException as exc:
                                display_result = "API ERROR - check Flask server"
                                display_color = (0, 0, 255)
                                print("Authorization request failed:", exc)

                    else:
                        last_box = None
                        display_plate = ""
                        display_result = "No plate detected"
                        display_color = (255, 255, 255)

                except Exception as exc:
                    print("ALPR inference error:", exc)
                    display_result = "ALPR inference error"
                    display_color = (0, 0, 255)

            if last_box is not None:
                x1, y1, x2, y2 = last_box
                cv2.rectangle(frame, (x1, y1), (x2, y2), display_color, 2)
                cv2.putText(
                    frame,
                    display_plate,
                    (x1, max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    display_color,
                    2,
                )

            # Result banner
            cv2.rectangle(
                frame, (0, 0), (frame.shape[1], 70), (30, 30, 30), -1
            )
            cv2.putText(
                frame,
                display_result[:100],
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                display_color,
                2,
            )
            cv2.putText(
                frame,
                "Q = quit | Gate movement disabled",
                (10, 56),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (220, 220, 220),
                1,
            )

            cv2.imshow("HSRP Smart Parking - ALPR + Authorization", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
