import cv2
import pytesseract

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

IMAGE_PATH = r"D:\HSRP_Parking\received_images\vehicle_20260924_121545.jpg"

image = cv2.imread(IMAGE_PATH)

if image is None:
    print("ERROR: Image could not be opened.")
    exit()

gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

gray = cv2.resize(
    gray,
    None,
    fx=2,
    fy=2,
    interpolation=cv2.INTER_CUBIC
)

gray = cv2.GaussianBlur(gray, (3, 3), 0)

_, threshold = cv2.threshold(
    gray,
    0,
    255,
    cv2.THRESH_BINARY + cv2.THRESH_OTSU
)

config = "--psm 7"

text = pytesseract.image_to_string(
    threshold,
    config=config
)

print("\nOCR RESULT:")
print(text)