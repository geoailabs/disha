"""
OpenCode Session Manager — Maps Disha conversation IDs to OpenCode session IDs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from llm.opencode.client import OpenCodeClient
from llm.opencode.server_manager import opencode_server_manager

logger = logging.getLogger("disha.opencode.session_manager")


class OpenCodeSessionManager:
    """Maintains mapping between Disha frontend conversations and OpenCode server sessions."""

    def __init__(self) -> None:
        self._conversation_to_session: dict[str, str] = {}
        self._client = OpenCodeClient(base_url=opencode_server_manager.base_url)

    def _get_cache_file(self, workspace: str | None) -> Path | None:
        if not workspace:
            return None
        ws_dir = Path(workspace) / ".disha"
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir / "opencode_sessions.json"

    def _load_cache(self, workspace: str | None) -> None:
        cache_file = self._get_cache_file(workspace)
        if cache_file and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._conversation_to_session.update(data)
            except Exception as e:
                logger.warning(f"Failed to read session cache: {e}")

    def _save_cache(self, workspace: str | None) -> None:
        cache_file = self._get_cache_file(workspace)
        if cache_file:
            try:
                cache_file.write_text(json.dumps(self._conversation_to_session, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to write session cache: {e}")

    async def get_or_create_session(
        self,
        conversation_id: str | None = None,
        title: str | None = None,
        workspace: str | None = None,
    ) -> str:
        """Retrieve existing OpenCode session or create a new one."""
        self._load_cache(workspace)

        conv_key = conversation_id or "default"
        existing_sid = self._conversation_to_session.get(conv_key)

        if existing_sid:
            session_info = await self._client.get_session(existing_sid)
            if session_info is not None:
                return existing_sid

        # Create new session
        new_sid = await self._client.create_session(title=title)
        self._conversation_to_session[conv_key] = new_sid
        self._save_cache(workspace)
        logger.info(f"Mapped conversation '{conv_key}' to OpenCode session '{new_sid}'")
        return new_sid

    def get_active_session_id(self, conversation_id: str | None = None) -> str | None:
        """Get currently mapped OpenCode session ID without creating a new one."""
        conv_key = conversation_id or "default"
        return self._conversation_to_session.get(conv_key)

    def clear_mapping(self, conversation_id: str | None = None, workspace: str | None = None) -> None:
        """Clear session mapping when conversation history is reset."""
        conv_key = conversation_id or "default"
        self._conversation_to_session.pop(conv_key, None)
        self._save_cache(workspace)

    def clear_session(self, conversation_id: str | None = None, workspace: str | None = None) -> None:
        """Alias for clear_mapping."""
        self.clear_mapping(conversation_id, workspace)


opencode_session_manager = OpenCodeSessionManager()
