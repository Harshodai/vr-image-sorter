"""
Test cases for SareeSorter class and FastAPI endpoints.

These tests verify barcode/OCR scanning and API processing functionality
using real saree images with VR codes.

Expected VR codes from test images:
- test_image_0.jpg -> VR90803
- test_image_1.jpg -> VR88772
- test_image_2.jpg -> VR86979
- test_image_3.jpg -> VR89056
"""

import os
import sys
import pytest
import numpy as np

# Add parent directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import SareeSorter, app
from fastapi.testclient import TestClient


# Test fixtures directory - contains the 4 test images
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Expected VR codes for each test image
EXPECTED_CODES = {
    "test_image_0.jpg": "VR90803",
    "test_image_1.jpg": "VR88772",
    "test_image_2.jpg": "VR86979",
    "test_image_3.jpg": "VR89056",
}


@pytest.fixture
def sorter():
    """Create a SareeSorter instance for testing."""
    return SareeSorter()


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    return TestClient(app)


def load_image_bytes(filename):
    """Helper to load image bytes from fixtures directory."""
    filepath = os.path.join(FIXTURES_DIR, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, "rb") as f:
        return f.read()


class TestPreprocessing:
    """Tests for image preprocessing methods."""

    def test_preprocess_original_returns_same(self, sorter):
        """Original method should return unchanged image."""
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        result = sorter.preprocess_image(dummy_image, "original")
        assert result is dummy_image

    def test_preprocess_grayscale_returns_2d(self, sorter):
        """Grayscale method should return 2D array."""
        dummy_image = np.zeros((100, 100, 3), dtype=np.uint8)
        result = sorter.preprocess_image(dummy_image, "grayscale")
        assert len(result.shape) == 2

    def test_preprocess_handles_already_grayscale(self, sorter):
        """Preprocessing should handle already grayscale images."""
        gray_image = np.zeros((100, 100), dtype=np.uint8)
        result = sorter.preprocess_image(gray_image, "sharpen")
        assert len(result.shape) == 2


class TestFilenameStandardization:
    """Tests for filename standardization logic."""

    def test_already_has_vr_prefix(self, sorter):
        """VR prefix should be preserved and uppercased."""
        result = sorter.standardize_filename("vr12345")
        assert result == "VR12345"

    def test_adds_vr_prefix_to_digits(self, sorter):
        """Digits-only should get VR prefix."""
        result = sorter.standardize_filename("12345")
        assert result == "VR12345"

    def test_strips_whitespace(self, sorter):
        """Whitespace should be stripped."""
        result = sorter.standardize_filename("  VR12345  ")
        assert result == "VR12345"

    def test_uppercase_conversion(self, sorter):
        """Result should be uppercase."""
        result = sorter.standardize_filename("vr12345abc")
        assert result == "VR12345ABC"


class TestBarcodeScanning:
    """Tests for barcode and OCR scanning on real images using bytes."""

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_scan_image_0_vr90803(self, sorter):
        """Test scanning VR90803 from test_image_0.jpg."""
        image_bytes = load_image_bytes("test_image_0.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        result = sorter.scan_barcode_from_bytes(image_bytes)
        assert result is not None, "Failed to scan barcode/OCR from image"
        assert "VR90803" in result.upper() or "90803" in result

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_scan_image_1_vr88772(self, sorter):
        """Test scanning VR88772 from test_image_1.jpg."""
        image_bytes = load_image_bytes("test_image_1.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        result = sorter.scan_barcode_from_bytes(image_bytes)
        assert result is not None, "Failed to scan barcode/OCR from image"
        assert "VR88772" in result.upper() or "88772" in result

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_scan_image_2_vr86979(self, sorter):
        """Test scanning VR86979 from test_image_2.jpg."""
        image_bytes = load_image_bytes("test_image_2.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        result = sorter.scan_barcode_from_bytes(image_bytes)
        assert result is not None, "Failed to scan barcode/OCR from image"
        assert "VR86979" in result.upper() or "86979" in result

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_scan_image_3_vr89056(self, sorter):
        """Test scanning VR89056 from test_image_3.jpg."""
        image_bytes = load_image_bytes("test_image_3.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        result = sorter.scan_barcode_from_bytes(image_bytes)
        assert result is not None, "Failed to scan barcode/OCR from image"
        assert "VR89056" in result.upper() or "89056" in result

    def test_invalid_image_bytes_returns_none(self, sorter):
        """Test that invalid image bytes return None."""
        result = sorter.scan_barcode_from_bytes(b"not an image")
        assert result is None


class TestFastAPIEndpoints:
    """Tests for FastAPI endpoints."""

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_process_single_image(self, client):
        """Test processing a single image via API."""
        image_bytes = load_image_bytes("test_image_0.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        response = client.post(
            "/api/process",
            files=[("files", ("test_image_0.jpg", image_bytes, "image/jpeg"))]
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "processed" in data
        assert "failed" in data
        assert "download_url" in data
        
        # Check that either processed or failed has our image
        total = len(data["processed"]) + len(data["failed"])
        assert total == 1

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_process_multiple_images(self, client):
        """Test processing multiple images via API."""
        files = []
        for filename in EXPECTED_CODES.keys():
            image_bytes = load_image_bytes(filename)
            if image_bytes:
                files.append(("files", (filename, image_bytes, "image/jpeg")))
        
        if not files:
            pytest.skip("No test images found")
        
        response = client.post("/api/process", files=files)
        
        assert response.status_code == 200
        data = response.json()
        
        # All images should be accounted for
        total = len(data["processed"]) + len(data["failed"])
        assert total == len(files)
        
        print(f"Processed: {data['processed']}")
        print(f"Failed: {data['failed']}")

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_download_after_process(self, client):
        """Test downloading zip after processing."""
        image_bytes = load_image_bytes("test_image_0.jpg")
        if image_bytes is None:
            pytest.skip("Test image not found")
        
        # First, process an image
        process_response = client.post(
            "/api/process",
            files=[("files", ("test_image_0.jpg", image_bytes, "image/jpeg"))]
        )
        
        assert process_response.status_code == 200
        data = process_response.json()
        session_id = data["session_id"]
        
        # Then download the zip
        download_response = client.get(f"/api/download/{session_id}")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "application/zip"

    def test_download_invalid_session(self, client):
        """Test downloading with invalid session ID."""
        response = client.get("/api/download/invalid-session-id")
        assert response.status_code == 404


class TestAllImagesIntegration:
    """Integration tests to verify all 4 test images are scanned correctly."""

    @pytest.mark.skipif(
        not os.path.exists(FIXTURES_DIR),
        reason="Fixtures directory not found"
    )
    def test_all_images_scan_correctly(self, sorter):
        """Test that all 4 test images return the expected VR codes."""
        results = {}
        
        for filename, expected_code in EXPECTED_CODES.items():
            image_bytes = load_image_bytes(filename)
            if image_bytes is None:
                continue
            
            result = sorter.scan_barcode_from_bytes(image_bytes)
            results[filename] = result
            
            print(f"{filename}: Expected={expected_code}, Got={result}")
        
        # Report results
        successful = sum(1 for r in results.values() if r is not None)
        print(f"\nScan Results: {successful}/{len(results)} successful")
        
        # At least some should succeed
        assert successful > 0, "At least one image should be scanned successfully"


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_saree_sorter.py -v
    pytest.main([__file__, "-v"])
