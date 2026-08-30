import cv2
import numpy as np
import logging

logger = logging.getLogger("vr-saree-sorter.scanner")

# Static kernels to prevent memory reallocation
KERNEL_SMALL = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))

def order_points(pts):
    """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left has smallest sum
    rect[2] = pts[np.argmax(s)]   # bottom-right has largest sum
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]   # top-right has smallest diff
    rect[3] = pts[np.argmax(d)]   # bottom-left has largest diff
    return rect

def upscale_if_small(image, min_width=800):
    """Upscale image if it's too small for reliable barcode reading."""
    h, w = image.shape[:2]
    if w < min_width:
        scale = min_width / w
        new_w = int(w * scale)
        new_h = int(h * scale)
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    return image

def extract_label_crops(image, mask, img_area):
    """Extract natural orientation label crops from a binary mask."""
    h_img, w_img = image.shape[:2]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    label_crops = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        # Sticker tags are typically between 0.2% and 30% of total image area
        if not (img_area * 0.002 < area < img_area * 0.30):
            continue
        
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 30 or ch < 20:
            continue
        aspect = max(cw, ch) / min(cw, ch)
        if aspect > 4.0:
            continue
        
        # 1. Natural padded bounding box crop (tight padding preserves crisp white label contrast)
        pad_x = 6
        pad_y = 6
        bbox_crop = image[max(0, y - pad_y):min(h_img, y + ch + pad_y),
                          max(0, x - pad_x):min(w_img, x + cw + pad_x)]
        
        area_ratio = area / img_area
        priority = 1.0 if (0.004 <= area_ratio <= 0.12) else 0.5
        label_crops.append((priority, area, bbox_crop))
    
    # Sort by priority (ideal tag size first), then area
    label_crops.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [crop for _, _, crop in label_crops]

def detect_label_regions(image):
    """
    Detect white/light rectangular label stickers in the image.
    Strategy: Progressive HSV saturation sweeps with size prioritization.
    """
    h, w = image.shape[:2]
    img_area = h * w
    
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    
    threshold_configs = [
        (40, 150),   # Crisp bright white stickers
        (30, 120),   # Off-white / shadow stickers
        (60, 140),   # Tinted labels
    ]
    
    for s_max, v_min in threshold_configs:
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[(sat < s_max) & (val > v_min)] = 255
        
        k_size = max(9, min(h, w) // 40)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_SMALL)
        
        label_crops = extract_label_crops(image, mask, img_area)
        if label_crops:
            logger.debug("Label detection hit at S<%d V>%d: %d candidates", s_max, v_min, len(label_crops))
            return label_crops
    
    return []

def standardize_filename(barcode_data):
    """Standardize output VRCode formats.
    The extraction pipeline (barcode.py + ocr.py) already ensures results
    contain 'VR'. This function normalizes casing and whitespace only.
    """
    clean_data = barcode_data.strip().upper()
    # Remove any non-alphanumeric characters
    clean_data = ''.join(c for c in clean_data if c.isalnum())
    return clean_data
