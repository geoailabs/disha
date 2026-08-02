"""GEE tile proxy router.

GEE map tiles require OAuth2 Bearer-token authentication.  The browser's
MapLibre renderer cannot set Authorization headers on XYZ tile requests, so
all tile fetching is proxied through this FastAPI endpoint.

The frontend stores only the map_id (the long hex token returned by
ee.data.getMapId) and requests tiles as:

    GET /api/gee/tiles/<map_id>/<z>/<x>/<y>

This endpoint appends the token to the EE tile URL and forwards the response.
Tiles are cached for 1 h per (map_id, z, x, y) tuple in a simple in-process
LRU cache so repeated map pans don't re-hit GEE.
"""

from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Response, Query

router = APIRouter()

_GEE_TILE_BASE = "https://earthengine.googleapis.com/v1/projects/earthengine-legacy/maps"
_TILE_TIMEOUT = 15.0

# ── Token management ──────────────────────────────────────────────────────────
# We reuse a single google-auth Credentials object and let it auto-refresh.
# Initialised lazily on the first tile request.

_creds = None
_creds_lock = asyncio.Lock()


def _find_creds_file(workspace: str | None = None) -> str | None:
    """Locate service account credentials in priority order."""
    env = os.environ.get("GOOGLE_EARTH_ENGINE_CREDS")
    if env:
        return env

    # 1. Workspace-specific hidden file
    if workspace:
        ws_file = Path(workspace) / ".disha" / "ee-service-account.json"
        if ws_file.exists():
            return str(ws_file)
        for f in sorted(Path(workspace).glob("ee-*.json")):
            return str(f)

    # 2. Project dev mode file in .tmp
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    dev_path = repo_root / ".tmp" / "gee-credentials.json"
    if dev_path.exists():
        return str(dev_path)

    # 3. Standard globs from CWD and project parents
    roots = [Path.cwd()]
    for p in [here.parent, here.parent.parent, here.parent.parent.parent,
              here.parent.parent.parent.parent]:
        if p not in roots:
            roots.append(p)
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.glob("ee-*.json")):
            return str(f)
        for f in sorted(root.glob("*.json")):
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("type") == "service_account":
                    return str(f)
            except Exception:
                pass
    return None


async def _get_token(workspace: str | None = None) -> str:
    """Return a valid Bearer token, refreshing if needed."""
    global _creds
    async with _creds_lock:
        if _creds is None:
            creds_path = _find_creds_file(workspace)
            if not creds_path:
                raise HTTPException(status_code=503,
                                    detail="GEE credentials not found on server")
            from google.oauth2 import service_account
            if os.path.isfile(creds_path):
                data = json.loads(Path(creds_path).read_text(encoding="utf-8"))
            else:
                data = json.loads(creds_path)
            _creds = service_account.Credentials.from_service_account_info(
                data,
                scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
            )

        if not _creds.valid:
            import google.auth.transport.requests
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, _creds.refresh, google.auth.transport.requests.Request()
            )

        return _creds.token  # type: ignore[return-value]


# ── Credentials configuration API ──────────────────────────────────────────────

@router.post("/credentials")
async def save_gee_credentials(body: dict, workspace: str | None = Query(None)):
    global _creds
    creds_json = body.get("credentials", "")
    
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent.parent
    if workspace:
        target = Path(workspace) / ".disha" / "ee-service-account.json"
    else:
        target = repo_root / ".tmp" / "gee-credentials.json"
        
    if not creds_json.strip():
        # Clear GEE credentials
        if target.exists():
            target.unlink()
        _creds = None
        from mcp_servers.gee_server import reset_gee_init
        reset_gee_init()
        return {"status": "cleared"}
        
    try:
        data = json.loads(creds_json)
        if not isinstance(data, dict) or data.get("type") != "service_account":
            raise ValueError("Credentials must be a Google Service Account JSON")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid service account JSON: {e}")
        
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    # Reset GEE process state to retry auth
    _creds = None
    from mcp_servers.gee_server import reset_gee_init
    reset_gee_init()
    
    # Try dynamic verify of Earth Engine
    from mcp_servers.gee_server import _ensure_gee
    ok, err = await _ensure_gee(workspace)
    if not ok:
        if target.exists():
            target.unlink()
        _creds = None
        reset_gee_init()
        raise HTTPException(status_code=400, detail=f"GEE Initialization failed: {err}")
        
    return {"status": "saved"}


# ── Tile proxy ────────────────────────────────────────────────────────────────

@router.get("/tiles/{map_id}/{z}/{x}/{y}")
async def gee_tile(map_id: str, z: int, x: int, y: int, workspace: str | None = Query(None)):
    """
    Proxy a GEE XYZ tile with server-side Bearer authentication.

    The frontend requests:
        /api/gee/tiles/{map_id}/{z}/{x}/{y}

    We forward to:
        https://earthengine.googleapis.com/v1/.../maps/{map_id}/tiles/{z}/{x}/{y}
    with the Authorization header added.
    """
    token = await _get_token(workspace)
    tile_url = f"{_GEE_TILE_BASE}/{map_id}/tiles/{z}/{x}/{y}"

    async with httpx.AsyncClient(timeout=_TILE_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(tile_url, headers={"Authorization": f"Bearer {token}"})

    if resp.status_code == 404:
        import base64
        empty = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        return Response(content=empty, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code,
                            detail=f"GEE tile server returned {resp.status_code}")

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=3600"},
    )
