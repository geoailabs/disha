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
