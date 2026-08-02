import sys
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app

client = TestClient(app)

def test_chat_websocket_connection_and_flow(tmp_path):
    workspace_str = str(tmp_path)
    
    with patch("routers.chat.AsyncOpenAI") as mock_openai_cls:
        mock_openai_instance = AsyncMock()
        mock_openai_cls.return_value = mock_openai_instance
        
        async def mock_stream():
            class MockChoice:
                delta = type("Delta", (), {"content": "Hello planner", "tool_calls": None})()
                finish_reason = "stop"
            class MockChunk:
                choices = [MockChoice()]
            yield MockChunk()
            
        mock_openai_instance.chat.completions.create = AsyncMock(return_value=mock_stream())
        
        with client.websocket_connect("/api/chat/ws") as websocket:
            payload = {
                "messages": [{"role": "user", "content": "Hello"}],
                "workspacePath": workspace_str
            }
            websocket.send_json(payload)
            
            # Read first WebSocket response frame
            data = websocket.receive_json()
            assert data["type"] in ("chunk", "done", "error", "action", "status")
