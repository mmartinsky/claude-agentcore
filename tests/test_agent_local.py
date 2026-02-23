"""
tests/test_agent_local.py — Local integration tests for the handler in main.py.

Calls handler() directly as an async generator — no HTTP server, no AWS.
Only requires ANTHROPIC_API_KEY in the environment.

Run:
    pytest tests/test_agent_local.py -v -s
"""

import asyncio
import os
import uuid

# When running tests inside an active Claude Code session, the CLAUDECODE env
# var is set and the SDK refuses to launch a nested claude subprocess. Unset it
# so the agent can run normally. In CI this var is absent, so this is a no-op.
os.environ.pop("CLAUDECODE", None)

from main import handler


def collect_frames(payload: dict) -> list[dict]:
    """Drain the handler async generator for the given payload."""
    async def _collect():
        return [frame async for frame in handler(payload)]
    return asyncio.run(_collect())


class TestHandlerLocal:

    def test_missing_prompt_returns_error(self):
        frames = collect_frames({})
        assert len(frames) == 1
        assert "error" in frames[0]

    def test_streaming_response_has_text(self):
        session_id = str(uuid.uuid4())
        frames = collect_frames({"prompt": "What is 2+2? One sentence.", "session_id": session_id})
        assert len(frames) > 0
        assert all("text" in f for f in frames), f"Missing text key: {frames}"
        assert not any("error" in f for f in frames), f"Error frame: {frames}"
        assert "".join(f["text"] for f in frames).strip()

    def test_session_id_echoed_in_response(self):
        session_id = str(uuid.uuid4())
        frames = collect_frames({"prompt": "Say hello.", "session_id": session_id})
        for f in frames:
            if "session_id" in f:
                assert f["session_id"] == session_id

    def test_two_independent_sessions(self):
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())
        frames_a = collect_frames({"prompt": "Say alpha.", "session_id": sid_a})
        frames_b = collect_frames({"prompt": "Say beta.", "session_id": sid_b})
        assert len(frames_a) > 0
        assert len(frames_b) > 0
