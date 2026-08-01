import sys
import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from streetview.downloader import get_google_key, lookup_metadata, panorama_jpeg

def test_get_google_key():
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "testkey123"}):
        assert get_google_key() == "testkey123"
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "", "GOOGLE_API_KEY": "testkey456"}):
        assert get_google_key() == "testkey456"

@patch("httpx.Client.get")
def test_lookup_metadata_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "OK",
        "pano_id": "google_pano_999",
        "location": {"lat": 30.73, "lng": 76.78},
        "date": "2026-08"
    }
    mock_get.return_value = mock_response

    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy"}):
        meta = lookup_metadata(30.73, 76.78)
        assert meta.found is True
        assert meta.pano_id == "google_pano_999"
        assert meta.lat == 30.73
        assert meta.lon == 76.78
        assert meta.date == "2026-08"

@patch("httpx.Client.get")
def test_panorama_jpeg_caching(mock_get, tmp_path):
    mock_meta_response = MagicMock()
    mock_meta_response.status_code = 200
    mock_meta_response.json.return_value = {
        "status": "OK",
        "pano_id": "pano_abc",
        "location": {"lat": 30.73, "lng": 76.78}
    }
    
    mock_img_response = MagicMock()
    mock_img_response.status_code = 200
    mock_img_response.content = b"fake-jpeg-bytes"

    mock_get.side_effect = [mock_meta_response, mock_img_response]

    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "dummy"}):
        # First call downloads and caches
        with patch("streetview.downloader.read_cached_image", return_value=None), \
             patch("streetview.downloader.write_cached_image") as mock_write:
            
            meta, img, cached = panorama_jpeg(30.73, 76.78)
            assert meta.found is True
            assert img == b"fake-jpeg-bytes"
            assert cached is False
            mock_write.assert_called_once_with("pano_abc", 3, b"fake-jpeg-bytes")
