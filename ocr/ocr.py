
import re
import cv2
import pytesseract


def recognize_plate(image_path):
    """
    Recognize text from a cropped number plate image.
    Returns the normalized plate text, or None if no text is found.
    """

    image = cv2.imread(image_path)

    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    # Convert to grayscale and enlarge the image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(
        gray, None, fx=3, fy=3,
        interpolation=cv2.INTER_CUBIC
    )

    # Improve contrast and binarize the plate
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    processed = cv2.threshold(
        gray, 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]

    # OCR configuration: single line, uppercase letters and digits
    config = (
    "--oem 3 --psm 7 "
    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    "-c load_system_dawg=0 "
    "-c load_freq_dawg=0"
)

    text = pytesseract.image_to_string(processed, config=config)

    # Remove spaces and punctuation
    plate = re.sub(r"[^A-Z0-9]", "", text.upper())

    return plate if plate else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: py ocr\\ocr.py path_to_plate_image.jpg")
        raise SystemExit(1)

    result = recognize_plate(sys.argv[1])
    print("Recognized plate:", result or "No text detected")
