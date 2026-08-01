import sys
import os
import builtins
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Helper to mock __import__ specifically for GIS libraries
orig_import = builtins.__import__
def custom_import(name, *args, **kwargs):
    if name in ["geopandas", "shapely", "fiona", "pyproj"]:
        return MagicMock()
    return orig_import(name, *args, **kwargs)

def test_diagnostics_unauthenticated_and_missing_keys():
    """Verify that diagnostics API behaves correctly when keys are missing."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GOOGLE_MAPS_API_KEY": ""}):
        response = client.get("/api/diagnostics")
        assert response.status_code == 200
        data = response.json()
        assert data["openai_api_key"]["status"] == "missing"
        assert data["google_maps_api_key"]["status"] == "missing"


@pytest.mark.asyncio
async def test_diagnostics_mocked_success():
    """Verify that diagnostics API reports valid/online status when mocked services respond correctly."""
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-openai-key",
        "GOOGLE_MAPS_API_KEY": "test-google-key"
    }):
        # Mock httpx responses for external checks
        with patch("httpx.AsyncClient.get") as mock_get:
            # Setup mock returns sequentially for Google Street View metadata, Overpass API, Nominatim status, OSRM status, Open-Meteo
            mock_responses = [
                # Google metadata check
                AsyncMock(status_code=200, json=lambda: {"status": "OK"}),
                # Overpass status check
                AsyncMock(status_code=200, text="Overpass API status ok"),
                # Nominatim status
                AsyncMock(status_code=200, json=lambda: {"status": "OK"}),
                # OSRM routing status
                AsyncMock(status_code=200, json=lambda: {"code": "Ok"}),
                # Open-Meteo weather status
                AsyncMock(status_code=200, json=lambda: {"latitude": 0})
            ]
            mock_get.side_effect = mock_responses
    
            # Mock OpenAI models list check
            with patch("openai.resources.models.AsyncModels.list", new_callable=AsyncMock) as mock_models_list, \
                 patch("builtins.__import__", side_effect=custom_import):
                mock_models_list.return_value = AsyncMock()
    
                response = client.get("/api/diagnostics")
                assert response.status_code == 200
                data = response.json()
                assert data["openai_api_key"]["status"] == "valid"
                assert data["google_maps_api_key"]["status"] == "valid"
                assert data["overpass_api"]["status"] == "online"
                assert data["nominatim_api"]["status"] == "online"
                assert data["osrm_api"]["status"] == "online"
                assert data["open_meteo"]["status"] == "online"
                assert data["libraries"]["status"] == "valid"
