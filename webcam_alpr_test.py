import cv2
from fast_alpr import ALPR


def main():
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(0)

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

    print("Webcam started. Show a number plate to the camera.")
    print("Press Q in the video window to quit.")

    frame_count = 0
    last_plate = ""
    last_detection = None

    try:
        while True:
            ret, frame = camera.read()
            if not ret:
                print("ERROR: Could not read a webcam frame.")
                break

            frame_count += 1
            # Run recognition every fifth frame to reduce CPU usage.
            if frame_count % 5 == 0:
                try:
                    detections = alpr.predict(frame)
                    if detections:
                        result = max(
                            detections,
                            key=lambda item: item.detection.confidence
                        )
                        box = result.detection.bounding_box
                        last_plate = result.ocr.text
                        last_detection = (
                            int(box.x1), int(box.y1),
                            int(box.x2), int(box.y2),
                            float(result.detection.confidence)
                        )
                        print(
                            f"Plate: {last_plate} | Detection confidence: "
                            f"{result.detection.confidence:.3f}"
                        )
                except Exception as exc:
                    print("ALPR inference error:", exc)

            if last_detection is not None:
                x1, y1, x2, y2, confidence = last_detection
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame, f"{last_plate} ({confidence:.2f})",
                    (x1, max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
                )

            cv2.imshow("HSRP Smart Parking - Webcam ALPR Test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
