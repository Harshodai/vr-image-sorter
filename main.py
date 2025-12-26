from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import easyocr
import re
import os
import tempfile
import shutil
import zipfile
from typing import List
import uuid

app = FastAPI(title="Saree Organizer API")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store temp directories for cleanup
temp_dirs = {}
reader = None


def get_reader():
    global reader
    if reader is None:
        reader = easyocr.Reader(['en'], verbose=False)
    return reader


def preprocess_image(image, method):
    if method == "original":
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if method == "grayscale":
        return gray
    if method == "sharpen":
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        return cv2.filter2D(gray, -1, kernel)
    if method == "threshold_otsu":
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh
    return gray


def scan_barcode(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return None

    methods = ["original", "grayscale", "sharpen", "threshold_otsu"]
    rotations = [0, 90, 180, 270]

    for method in methods:
        processed = preprocess_image(image, method)
        for angle in rotations:
            if angle == 90:
                img = cv2.rotate(processed, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                img = cv2.rotate(processed, cv2.ROTATE_180)
            elif angle == 270:
                img = cv2.rotate(processed, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                img = processed

            barcodes = decode(img)
            for barcode in barcodes:
                data = barcode.data.decode("utf-8")
                if data:
                    return data

    # Fallback to OCR
    try:
        ocr_reader = get_reader()
        results = ocr_reader.readtext(image)
        for (_, text, _) in results:
            clean = text.replace(" ", "").upper()
            if "VR" in clean:
                match = re.search(r"VR\d+", clean)
                if match:
                    return match.group(0)
    except:
        pass

    return None


def standardize_filename(data):
    clean = data.strip().upper()
    if not clean.startswith("VR") and clean.isdigit():
        return f"VR{clean}"
    return clean


@app.post("/api/process")
async def process_images(files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    output_dir = os.path.join(temp_dir, "output")
    os.makedirs(output_dir)

    processed = []
    failed = []

    for file in files:
        try:
            contents = await file.read()
            result = scan_barcode(contents)

            if result:
                ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
                new_name = f"{standardize_filename(result)}{ext}"
                output_path = os.path.join(output_dir, new_name)

                counter = 1
                while os.path.exists(output_path):
                    new_name = f"{standardize_filename(result)}_{counter}{ext}"
                    output_path = os.path.join(output_dir, new_name)
                    counter += 1

                with open(output_path, "wb") as f:
                    f.write(contents)

                processed.append({
                    "original_name": file.filename,
                    "new_name": new_name
                })
            else:
                failed.append({"original_name": file.filename})
        except Exception as e:
            failed.append({"original_name": file.filename})

    # Create ZIP
    zip_path = os.path.join(temp_dir, "output.zip")
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for f in os.listdir(output_dir):
            zf.write(os.path.join(output_dir, f), f)

    temp_dirs[session_id] = temp_dir

    return {
        "session_id": session_id,
        "processed": processed,
        "failed": failed,
        "download_url": f"/api/download/{session_id}"
    }


@app.get("/api/download/{session_id}")
async def download_zip(session_id: str):
    if session_id not in temp_dirs:
        raise HTTPException(status_code=404, detail="Session not found")

    zip_path = os.path.join(temp_dirs[session_id], "output.zip")
    return FileResponse(zip_path, filename="saree_organized.zip", media_type="application/zip")


@app.get("/health")
async def health():
    return {"status": "ok"}