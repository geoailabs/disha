import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_files_list_endpoint(tmp_path):
    workspace_str = str(tmp_path)
    (tmp_path / "sample.geojson").write_text('{"type": "FeatureCollection", "features": []}')
    
    response = client.get("/api/files", params={"path": workspace_str, "workspace": workspace_str})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    filenames = [f["name"] for f in data["items"]]
    assert "sample.geojson" in filenames

def test_artifacts_crud_endpoint(tmp_path):
    workspace_str = str(tmp_path)
    
    # Create artifact via POST /api/artifacts
    art_payload = {
        "title": "Proposed Site Plan",
        "artifact_type": "note",
        "format": "markdown",
        "content": "# Site Plan\n\nProposed residential zone."
    }
    response = client.post("/api/artifacts", json=art_payload, params={"workspace": workspace_str})
    assert response.status_code == 201
    created = response.json()
    assert "id" in created
    art_id = created["id"]
    
    # List artifacts via GET /api/artifacts
    response = client.get("/api/artifacts", params={"workspace": workspace_str})
    assert response.status_code == 200
    artifacts = response.json()
    assert any(a["id"] == art_id for a in artifacts)
    
    # Delete artifact
    response = client.delete(f"/api/artifacts/{art_id}", params={"workspace": workspace_str})
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_sync_keys_and_key_status_endpoint():
    import os

    sync_payload = {
        "openai_api_key": "export OPENAI_API_KEY=\"sk-test-mock-key-12345678\"",
        "google_maps_api_key": "AIzaSyMockGoogleMapsKey12345678",
        "gee_credentials": '{"type": "service_account", "project_id": "test-gee"}',
        "mapillary_token": "MLY|mock_mapillary_token_12345",
    }
    resp = client.post("/api/chat/sync-keys", json=sync_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["openai"] is True
    assert resp.json()["google_maps"] is True
    assert resp.json()["gee"] is True
    assert resp.json()["mapillary"] is True

    # Check os.environ
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-mock-key-12345678"
    assert os.environ.get("GOOGLE_MAPS_API_KEY") == "AIzaSyMockGoogleMapsKey12345678"
    assert "test-gee" in os.environ.get("GOOGLE_EARTH_ENGINE_CREDS", "")
    assert os.environ.get("MAPILLARY_ACCESS_TOKEN") == "MLY|mock_mapillary_token_12345"

    # Check /api/chat/key-status returns all 4 as True
    status_resp = client.get("/api/chat/key-status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["openai"] is True
    assert status_data["google_maps"] is True
    assert status_data["gee"] is True
    assert status_data["mapillary"] is True

    # Test clearing keys
    clear_payload = {
        "openai_api_key": "",
        "google_maps_api_key": "",
        "gee_credentials": "",
        "mapillary_token": "",
    }
    client.post("/api/chat/sync-keys", json=clear_payload)
    assert not os.environ.get("OPENAI_API_KEY")
    assert not os.environ.get("GOOGLE_MAPS_API_KEY")
    assert not os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
    assert not os.environ.get("MAPILLARY_ACCESS_TOKEN")


def test_validate_key_normalization():
    # Invalid short key
    resp = client.post("/api/chat/validate-key", json={"api_key": "short"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert "sk-" in data["error"]

