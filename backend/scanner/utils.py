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
    """Extract perspective-corrected label crops from a binary mask."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    label_crops = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (img_area * 0.005 < area < img_area * 0.95):
            continue
        
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        box = np.intp(box)
        
        rect_w, rect_h = rect[1]
        if rect_w == 0 or rect_h == 0:
            continue
        aspect = max(rect_w, rect_h) / min(rect_w, rect_h)
        if aspect > 5.0:
            continue
        
        src_pts = box.astype(np.float32)
        src_pts = order_points(src_pts)
        
        dst_w = int(max(rect_w, rect_h))
        dst_h = int(min(rect_w, rect_h))
        if dst_w < 50 or dst_h < 30:
            continue
        
        dst_pts = np.array([
            [0, 0], [dst_w - 1, 0],
            [dst_w - 1, dst_h - 1], [0, dst_h - 1]
        ], dtype=np.float32)
        
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        warped = cv2.warpPerspective(image, M, (dst_w, dst_h))
        
        pad = 10
        padded = cv2.copyMakeBorder(warped, pad, pad, pad, pad,
                                    cv2.BORDER_CONSTANT, value=(255, 255, 255))
        
        label_crops.append((area, padded))
    
    label_crops.sort(key=lambda x: x[0], reverse=True)
    return [crop for _, crop in label_crops]

def detect_label_regions(image):
    """
    Detect white/light rectangular label stickers in the image.
    Strategy: Progressive HSV saturation sweeps.
    """
    h, w = image.shape[:2]
    img_area = h * w
    
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    
    threshold_configs = [
        (25, 120),   (40, 120),   (60, 140),
    ]
    
    for s_max, v_min in threshold_configs:
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[(sat < s_max) & (val > v_min)] = 255
        
        k_size = max(15, min(h, w) // 25)
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
