"""
main.py — BedrockAgentCoreApp entrypoint wrapping the Claude Agent SDK.

The handler is an async generator. BedrockAgentCoreApp detects this and
automatically streams the output as Server-Sent Events
(Content-Type: text/event-stream), preventing gateway timeouts on long
agent runs.

Invocation payload:
    {"prompt": "your question here"}

Optional:
    {"prompt": "...", "session_id": "uuid-string"}

session_id is used to create an isolated working directory under /tmp so
concurrent invocations do not interfere with each other's file operations.
"""

import logging
import os
import sys

import boto3
import watchtower
from bedrock_agentcore import BedrockAgentCoreApp

from agent import run_agent

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Wire up CloudWatch Logs if CW_LOG_GROUP is set (injected by deploy.sh).
# Falls back gracefully if boto3 credentials aren't available (e.g. local dev).
_cw_log_group = os.environ.get("CW_LOG_GROUP")
if _cw_log_group:
    try:
        _cw_handler = watchtower.CloudWatchLogHandler(
            log_group_name=_cw_log_group,
            log_stream_name="app-logs",
            boto3_client=boto3.client("logs", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")),
            create_log_group=False,
        )
        _cw_handler.setLevel(logging.INFO)
        logging.root.addHandler(_cw_handler)
        logger.info("CloudWatch Logs handler active → %s", _cw_log_group)
    except Exception as _e:
        logger.warning("CloudWatch Logs handler setup failed: %s", _e)

app = BedrockAgentCoreApp()


@app.entrypoint
async def handler(payload: dict):
    """
    Main entrypoint. Receives the JSON-parsed request body as a Python dict.

    BedrockAgentCoreApp calls json.loads() before invoking this handler,
    so payload is already a dict — do NOT call json.loads(payload).

    Because this is an async generator (uses yield), BedrockAgentCoreApp
    wraps it in a StreamingResponse with media_type="text/event-stream".
    Each yielded value is JSON-serialised and sent as:
        data: <json>\n\n
    """
    logger.info("payload: %s", payload)
    prompt = payload.get("prompt", "")
    session_id = payload.get("session_id", "default")

    if not prompt:
        yield {"error": "Missing required field: prompt"}
        return

    # Isolate file-system work per session to avoid concurrent collisions.
    work_dir = f"/tmp/agent-sessions/{session_id}"
    os.makedirs(work_dir, exist_ok=True)

    logger.info("session=%s prompt_len=%d", session_id, len(prompt))

    result = await run_agent(prompt=prompt, cwd=work_dir)
    yield {"text": result, "session_id": session_id}


if __name__ == "__main__":
    app.run(port=8080)
