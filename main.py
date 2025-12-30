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
from typing import List, Optional
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
# Store temp directories with timestamp for cleanup
temp_dirs = {}

def cleanup_session(session_id: str):
    """Refactored cleanup logic"""
    if session_id in temp_dirs:
        path = temp_dirs[session_id]["path"]
        try:
            if os.path.exists(path):
                shutil.rmtree(path)
            print(f"Cleaned up session {session_id}")
        except Exception as e:
            print(f"Error cleaning up session {session_id}: {e}")
        finally:
            del temp_dirs[session_id]

class SareeSorter:
    def __init__(self):
        self.reader = None # Lazy load

    def get_reader(self):
        if self.reader is None:
            print("Initializing OCR Reader (this may take a moment)...")
            # verbose=False prevents encoding errors on Windows console
            self.reader = easyocr.Reader(['en'], verbose=False, gpu=False) 
        return self.reader

    def preprocess_image(self, image, method):
        if method == "original":
            return image
        
        # Convert to grayscale if needing processing
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        if method == "grayscale":
            return gray
        
        if method == "sharpen":
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            return cv2.filter2D(gray, -1, kernel)
        
        if method == "threshold_otsu":
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return thresh
        
        if method == "adaptive_threshold":
            return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

        return gray

    def decode_frame(self, image):
        try:
            barcodes = decode(image)
            for barcode in barcodes:
                barcode_data = barcode.data.decode("utf-8")
                if barcode_data:
                    return barcode_data
        except Exception as e:
            print(f"Error in decode_frame: {e}")
        return None

    def scan_ocr(self, image):
        try:
            reader = self.get_reader()
            
            # Preprocessing methods for OCR to handle noise/patterns
            methods = ["grayscale", "threshold_otsu", "original"]
            rotations = [0, 90, 180, 270]

            for method in methods:
                processed = self.preprocess_image(image, method)
                
                for angle in rotations:
                    # Rotate
                    if angle == 0:
                        img_to_scan = processed
                    elif angle == 90:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_CLOCKWISE)
                    elif angle == 180:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_180)
                    elif angle == 270:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    else:
                        img_to_scan = processed

                    # Scan
                    try:
                        results = reader.readtext(img_to_scan)
                        for (bbox, text, prob) in results:
                            # Clean text
                            clean = text.replace(" ", "").upper()
                            # Strict matching for VR followed by digits
                            if "VR" in clean:
                                match = re.search(r"VR\d+", clean)
                                if match:
                                    print(f"Success: OCR Found {match.group(0)} with {method} at {angle} deg")
                                    return match.group(0)
                    except Exception as e:
                        continue 
        except Exception as e:
            print(f"OCR specific error: {e}")
        return None

    def scan_barcode_from_bytes(self, image_bytes) -> Optional[str]:
        """
        Attempts to scan a barcode from image bytes.
        """
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            original_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if original_image is None:
                print("Error: Could not decode image bytes")
                return None
        except Exception as e:
            print(f"Exception reading image bytes: {e}")
            return None

        # 1. Try Barcode Scan (Fast)
        methods = ["original", "grayscale", "sharpen", "threshold_otsu", "adaptive_threshold"]
        rotations = [0, 90, 180, 270]

        for method in methods:
            processed_img = self.preprocess_image(original_image, method)
            for angle in rotations:
                if angle == 0:
                    img_to_scan = processed_img
                elif angle == 90:
                    img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180:
                    img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_180)
                elif angle == 270:
                    img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                else:
                    img_to_scan = processed_img
                
                result = self.decode_frame(img_to_scan)
                if result:
                    print(f"Success: Barcode Found {result} with method {method} at {angle} deg")
                    return result
        
        # 2. Try OCR (Slow but fallback)
        print("Barcode scan failed. Attempting OCR...")
        ocr_result = self.scan_ocr(original_image)
        if ocr_result:
            return ocr_result

        return None

    def standardize_filename(self, barcode_data):
        clean_data = barcode_data.strip()
        if not clean_data.upper().startswith("VR"):
            if clean_data.isdigit():
                 return f"VR{clean_data}"
        return clean_data.upper()

# Global sorter instance
sorter = SareeSorter()

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
            # method renamed to be clearer it takes bytes
            result = sorter.scan_barcode_from_bytes(contents)
            
            if result:
                ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
                clean_name = sorter.standardize_filename(result)
                new_name = f"{clean_name}{ext}"
                output_path = os.path.join(output_dir, new_name)
                
                counter = 1
                while os.path.exists(output_path):
                    new_name = f"{clean_name}_{counter}{ext}"
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
            print(f"Error processing file {file.filename}: {e}")
            failed.append({"original_name": file.filename})
    
    # Create ZIP
    if not os.listdir(output_dir):
        # Handle case where everything failed? 
        # We can still make an empty zip or just return what we have.
        pass

    zip_path = os.path.join(temp_dir, "output.zip")
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for f in os.listdir(output_dir):
            zf.write(os.path.join(output_dir, f), f)
    
    import time
    temp_dirs[session_id] = {
        "path": temp_dir,
        "created_at": time.time()
    }
    
    # Trigger cleanup of old sessions (older than 1 hour)
    current_time = time.time()
    expired = [sid for sid, data in temp_dirs.items() if current_time - data["created_at"] > 3600]
    for sid in expired:
        cleanup_session(sid)
    
    return {
        "session_id": session_id,
        "processed": processed,
        "failed": failed,
        "download_url": f"/api/download/{session_id}"
    }

from fastapi import BackgroundTasks

@app.get("/api/download/{session_id}")
async def download_zip(session_id: str, background_tasks: BackgroundTasks):
    if session_id not in temp_dirs:
        raise HTTPException(status_code=404, detail="Session not found")
    
    zip_path = os.path.join(temp_dirs[session_id], "output.zip")
    if not os.path.exists(zip_path):
         raise HTTPException(status_code=404, detail="Zip file not found")
         
    # Schedule cleanup after response is sent
    background_tasks.add_task(cleanup_session, session_id)
    
    return FileResponse(zip_path, filename="saree_organized.zip", media_type="application/zip")

@app.get("/health")
async def health():
    return {"status": "ok"}
