"""
OpenCode Server Manager — Spawns and monitors headless `opencode serve` process.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("disha.opencode.server_manager")

_DEFAULT_PORT = int(os.environ.get("OPENCODE_PORT", "4096"))
_DEFAULT_HOST = os.environ.get("OPENCODE_HOST", "127.0.0.1")


class OpenCodeServerManager:
    """Manages the lifecycle of the headless `opencode serve` process."""

    def __init__(self, port: int = _DEFAULT_PORT, host: str = _DEFAULT_HOST) -> None:
        self.port = port
        self.host = host
        self.base_url = f"http://{host}:{port}"
        self.process: subprocess.Popen | None = None
        self._is_started_by_us = False

    def is_opencode_installed(self) -> bool:
        """Check if opencode executable is present in PATH."""
        return bool(shutil.which("opencode"))

    async def is_server_healthy(self) -> bool:
        """Check if opencode serve is reachable and answering HTTP requests."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/session")
                return resp.status_code == 200
        except Exception:
            return False

    def ensure_opencode_config(self, workspace_path: str | None = None) -> None:
        """Ensure opencode.json exists in workspace/root with disha_tools MCP server configured."""
        backend_dir = Path(__file__).resolve().parent.parent.parent
        root_dir = backend_dir.parent.parent
        config_dir = Path(workspace_path) if workspace_path else root_dir

        mcp_script = backend_dir / "llm" / "opencode" / "mcp_server.py"

        # Locate Python executable inside virtualenv if available
        python_exe = sys.executable

        config_data: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "disha_tools": {
                    "type": "local",
                    "command": [str(python_exe), str(mcp_script)],
                }
            },
            "permission": {
                "bash": "allow",
                "edit": "allow",
                "read": "allow",
                "glob": "allow",
                "grep": "allow",
                "list": "allow",
                "task": "allow",
                "todowrite": "allow",
                "question": "allow",
                "websearch": "allow",
                "webfetch": "allow",
            },
        }

        # Write project-level opencode.json
        config_path = config_dir / "opencode.json"
        try:
            config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
            logger.info(f"Configured OpenCode MCP at {config_path}")
        except Exception as e:
            logger.warning(f"Failed to write opencode.json at {config_path}: {e}")

    async def ensure_server_running(self, workspace_path: str | None = None) -> bool:
        """Ensure OpenCode server is active, starting it if necessary."""
        if await self.is_server_healthy():
            return True

        if not self.is_opencode_installed():
            logger.warning("opencode CLI binary not found in PATH.")
            return False

        self.ensure_opencode_config(workspace_path)

        backend_dir = Path(__file__).resolve().parent.parent.parent
        cwd = workspace_path if workspace_path else str(backend_dir.parent.parent)

        cmd = [
            "opencode",
            "serve",
            "--port", str(self.port),
            "--hostname", self.host,
        ]

        logger.info(f"Starting OpenCode server: {' '.join(cmd)} in {cwd}")

        env = os.environ.copy()
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._is_started_by_us = True
        except Exception as e:
            logger.error(f"Failed to launch opencode process: {e}")
            return False

        # Poll until healthy
        for _ in range(30):
            await asyncio.sleep(0.5)
            if await self.is_server_healthy():
                logger.info(f"OpenCode server is ready on {self.base_url}")
                return True

        logger.error(f"OpenCode server failed to become healthy on {self.base_url}")
        return False

    def stop_server(self) -> None:
        """Terminate the server process if it was started by this instance."""
        if self._is_started_by_us and self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3.0)
                logger.info("OpenCode server terminated.")
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
                self._is_started_by_us = False


opencode_server_manager = OpenCodeServerManager()
