"""
OpenCode Agent Orchestrator for Disha.

Coordinates agent execution between OpenCode Server, the active WebSocket connection,
the 7+1 Domain Hubs, and MapLibre cartographic actions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import WebSocket

from llm.opencode.client import OpenCodeClient
from llm.opencode.server_manager import opencode_server_manager
from llm.opencode.session_manager import opencode_session_manager

logger = logging.getLogger("disha.opencode.orchestrator")


async def run_opencode_agent(
    user_content: str,
    ws: WebSocket,
    map_context: dict[str, Any] | None = None,
    chat_attachments: list[dict[str, Any]] | None = None,
    active_image: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    stop_event: asyncio.Event | None = None,
    system_prompt: str | None = None,
    workspace: str | None = None,
) -> None:
    """
    Execute a conversational reasoning turn through the OpenCode runtime.
    Streams text deltas, tool badges, and map actions over the active WebSocket.
    """
    # 1. Ensure OpenCode Server is running
    server_ready = await opencode_server_manager.ensure_server_running(workspace)
    if not server_ready:
        logger.error("OpenCode server is not available.")
        await ws.send_text(json.dumps({
            "type": "error",
            "code": "upstream",
            "message": "OpenCode agent server is not available. Check installation or toggle USE_OPENCODE=false.",
        }))
        await ws.send_text(json.dumps({"type": "end"}))
        return

    client = OpenCodeClient(base_url=opencode_server_manager.base_url)

    # 2. Get or create OpenCode session
    session_id = await opencode_session_manager.get_or_create_session(
        conversation_id=conversation_id,
        title=user_content[:40],
        workspace=workspace,
    )

    # 3. Assemble dynamic contextual prompt
    prompt_sections: list[str] = []

    if system_prompt:
        prompt_sections.append(f"[SYSTEM CONTEXT]\n{system_prompt}")

    if map_context:
        prompt_sections.append(f"[CURRENT MAP STATE]\n{json.dumps(map_context, indent=2)}")

    prompt_sections.append(user_content)
    full_prompt_text = "\n\n".join(prompt_sections)

    # Combine attachments for vision
    all_attachments: list[dict[str, Any]] = []
    if active_image and active_image.get("base64"):
        all_attachments.append(active_image)
    if chat_attachments:
        all_attachments.extend(chat_attachments)

    # 4. Stream events and send prompt
    stream_task = asyncio.create_task(_consume_opencode_stream(client, session_id, ws, stop_event))

    try:
        sent = await client.send_prompt_async(
            session_id=session_id,
            text=full_prompt_text,
            attachments=all_attachments if all_attachments else None,
        )

        if not sent:
            await ws.send_text(json.dumps({
                "type": "error",
                "code": "internal",
                "message": "Failed to send prompt to OpenCode server.",
            }))
            await ws.send_text(json.dumps({"type": "end"}))
            return

        # Await completion of streaming task
        await stream_task

    except asyncio.CancelledError:
        logger.info(f"Aborting OpenCode session {session_id} due to task cancellation")
        await client.abort_session(session_id)
        if not stream_task.done():
            stream_task.cancel()
        raise
    except Exception as e:
        logger.exception(f"OpenCode agent execution error: {e}")
        await ws.send_text(json.dumps({
            "type": "error",
            "code": "internal",
            "message": f"OpenCode execution error: {str(e)}",
        }))
        await ws.send_text(json.dumps({"type": "end"}))
    finally:
        if not stream_task.done():
            stream_task.cancel()


async def _consume_opencode_stream(
    client: OpenCodeClient,
    session_id: str,
    ws: WebSocket,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Listen to OpenCode SSE stream and forward events to Disha WebSocket."""
    seen_part_deltas: set[str] = set()

    try:
        async for event in client.stream_events():
            if stop_event and stop_event.is_set():
                await client.abort_session(session_id)
                break

            event_type = event.get("type", "")
            props = event.get("properties", {})
            event_sid = props.get("sessionID")

            # Only handle events for our active session
            if event_sid and event_sid != session_id:
                continue

            if event_type == "message.part.delta":
                delta = props.get("delta", "")
                if delta:
                    await ws.send_text(json.dumps({
                        "type": "stream",
                        "content": delta,
                    }))

            elif event_type == "message.part.updated":
                part = props.get("part", {})
                ptype = part.get("type")

                # If a tool is invoked by OpenCode
                if ptype == "tool-invocation":
                    tool_name = part.get("tool", "")
                    tool_args = part.get("input", {})
                    await ws.send_text(json.dumps({
                        "type": "tool_use",
                        "tool": tool_name,
                        "args": tool_args,
                    }))

            elif event_type == "session.idle":
                # Turn execution completed
                await ws.send_text(json.dumps({"type": "end"}))
                break

            elif event_type == "session.status":
                status = props.get("status", {})
                if status.get("type") == "idle":
                    # Check if session is finished
                    pass

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"Error in OpenCode event stream listener: {e}")
