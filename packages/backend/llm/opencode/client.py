"""
Async HTTP/SSE Client for communicating with the headless OpenCode Server.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import httpx

logger = logging.getLogger("disha.opencode.client")


class OpenCodeClient:
    """Client for OpenCode Server REST and SSE endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:4096") -> None:
        self.base_url = base_url.rstrip("/")

    async def create_session(self, title: str | None = None) -> str:
        """Create a new OpenCode session and return its session ID."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            payload: dict[str, Any] = {}
            if title:
                payload["title"] = title
            resp = await client.post("/session", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session metadata or None if not found."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
                resp = await client.get(f"/session/{session_id}")
                if resp.status_code == 200:
                    return resp.json()
                return None
        except Exception:
            return None

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Get all messages for a session."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            resp = await client.get(f"/session/{session_id}/message")
            resp.raise_for_status()
            return resp.json()

    async def get_todo(self, session_id: str) -> list[dict[str, Any]]:
        """Get the active agent plan / todo items for a session."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
                resp = await client.get(f"/session/{session_id}/todo")
                if resp.status_code == 200:
                    return resp.json()
                return []
        except Exception:
            return []

    async def send_prompt_async(
        self,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send user prompt asynchronously to OpenCode session."""
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]

        if attachments:
            for att in attachments:
                if att.get("base64"):
                    mtype = att.get("mime_type", "image/png")
                    parts.append({
                        "type": "image",
                        "image": {
                            "mime": mtype,
                            "data": att["base64"],
                        }
                    })

        async with httpx.AsyncClient(base_url=self.base_url, timeout=15.0) as client:
            resp = await client.post(
                f"/session/{session_id}/prompt_async",
                json={"parts": parts},
            )
            return resp.status_code in (200, 204)

    async def abort_session(self, session_id: str) -> bool:
        """Abort in-flight processing on the specified session."""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
                resp = await client.post(f"/session/{session_id}/abort")
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to abort OpenCode session {session_id}: {e}")
            return False

    async def stream_events(self) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to the OpenCode SSE event stream and yield parsed event payloads."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=None) as client:
            async with client.stream("GET", "/event") as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            event_data = json.loads(data_str)
                            yield event_data
                        except Exception:
                            continue
