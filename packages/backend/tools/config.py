"""Shared runtime config helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent.parent
_MODEL_CONFIG_PATH = _BACKEND_DIR / "model_config.json"
_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")


def get_model() -> str:
    paths_to_check = [
        Path(os.environ.get("DISHA_MODEL_CONFIG", "")),
        _BACKEND_DIR / "model_config.json",
        Path.home() / ".disha" / "model_config.json",
    ]
    for p in paths_to_check:
        if p and p.is_file():
            try:
                data = json.loads(p.read_text())
                m = data.get("model")
                if m:
                    return m
            except Exception:
                pass
    return _DEFAULT_MODEL
