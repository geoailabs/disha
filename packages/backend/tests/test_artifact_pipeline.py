import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tools.task_pipeline import patch_content_with_real_paths


def test_task_pipeline_patch_no_duplicate_assignments():
    """Verify patch_content_with_real_paths assigns unique assets to each image reference."""
    content = (
        "# Regional Study\n\n"
        "## Region A\n"
        "![Region A Boundary](artifacts_store/10.jpg)\n\n"
        "## Region B\n"
        "![Region B Boundary](artifacts_store/10.jpg)\n"
    )
    asset_results = {
        "call_1": {"file_path": "artifacts_store/10.jpg", "title": "Region A Boundary"},
        "call_2": {"file_path": "artifacts_store/11.jpg", "title": "Region B Boundary"},
    }

    patched = patch_content_with_real_paths(content, asset_results)
    assert "artifacts_store/10.jpg" in patched
    assert "artifacts_store/11.jpg" in patched
    # Ensure neither path is duplicated
    assert patched.count("artifacts_store/10.jpg") == 1
    assert patched.count("artifacts_store/11.jpg") == 1


@pytest.mark.asyncio
async def test_create_artifact_blocks_duplicate_images():
    """Verify that _execute_tool blocks create_artifact when duplicate images are detected."""
    from routers.chat import _execute_tool

    ws = AsyncMock()
    duplicate_content = (
        "# Tri-City Boundary Report\n\n"
        "## City A Boundary\n"
        "![City A](artifacts_store/99.jpg)\n\n"
        "## City B Boundary\n"
        "![City B](artifacts_store/99.jpg)\n"
    )

    args = {
        "title": "Boundary Report",
        "format": "pdf",
        "content": duplicate_content,
    }

    res_str = await _execute_tool("create_artifact", args, ws, messages=[])
    res = json.loads(res_str)

    assert res.get("status") == "blocked"
    assert "Duplicate image references detected" in res.get("error", "")


@pytest.mark.asyncio
async def test_create_artifact_blocks_insufficient_images_for_sections():
    """Verify that _execute_tool blocks create_artifact when visual sections exceed unique images."""
    from routers.chat import _execute_tool

    ws = AsyncMock()
    content_with_many_sections = (
        "# Multi-Area Plan\n\n"
        "## Area 1 Boundary\n"
        "![Area 1](artifacts_store/101.jpg)\n\n"
        "## Area 2 Boundary\n"
        "Some details about area 2.\n\n"
        "## Area 3 Boundary\n"
        "Some details about area 3.\n"
    )

    args = {
        "title": "Multi-Area Plan",
        "format": "pdf",
        "content": content_with_many_sections,
    }

    res_str = await _execute_tool("create_artifact", args, ws, messages=[])
    res = json.loads(res_str)

    assert res.get("status") == "blocked"
    assert "Every visual section MUST have its own dedicated exported map figure" in res.get("error", "")
