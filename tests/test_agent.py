"""
tests/test_agent.py — Integration tests for the deployed AgentCore Runtime.

No mocking. Real boto3 calls to the live AWS AgentCore Runtime.

The agent_arn fixture polls until the runtime reaches READY status (up to
10 minutes, checking every 2 seconds), then each test makes a single real
invocation and asserts on the SSE streaming response.

Prerequisites:
    - deploy.sh has been run successfully
    - AWS credentials are configured (env vars or ~/.aws/credentials)
    - pytest is installed: pip install pytest

Run:
    pytest tests/test_agent.py -v -s
"""

import json
import os
import time
import uuid

import boto3
import pytest

# ── Configuration ──────────────────────────────────────────────────────────────

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
AGENT_NAME = "claude_agentcore_agent"
CONTROL_ENDPOINT = f"https://bedrock-agentcore-control.{REGION}.amazonaws.com"
DATA_ENDPOINT = f"https://bedrock-agentcore.{REGION}.amazonaws.com"
READY_TIMEOUT_S = 600  # 10 minutes
POLL_INTERVAL_S = 2


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_agent_arn() -> str:
    """Look up the AgentCore Runtime ARN by name."""
    client = boto3.client(
        "bedrock-agentcore-control",
        region_name=REGION,
        endpoint_url=CONTROL_ENDPOINT,
    )
    for r in client.list_agent_runtimes().get("agentRuntimes", []):
        if r["agentRuntimeName"] == AGENT_NAME:
            return r["agentRuntimeArn"]
    raise RuntimeError(
        f"No AgentCore Runtime named '{AGENT_NAME}' found in {REGION}. "
        "Run deploy.sh first."
    )


def wait_for_ready(arn: str) -> None:
    """
    Poll list_agent_runtimes every POLL_INTERVAL_S seconds until the runtime
    status is READY. Raises on terminal failure states or timeout.
    """
    client = boto3.client(
        "bedrock-agentcore-control",
        region_name=REGION,
        endpoint_url=CONTROL_ENDPOINT,
    )
    deadline = time.time() + READY_TIMEOUT_S
    while time.time() < deadline:
        for r in client.list_agent_runtimes().get("agentRuntimes", []):
            if r["agentRuntimeArn"] == arn:
                status = r.get("status", "UNKNOWN")
                if status == "READY":
                    return
                if status in ("FAILED", "DELETING", "DELETED"):
                    raise RuntimeError(
                        f"Runtime entered terminal status: {status}"
                    )
                print(f"  Status: {status} — waiting {POLL_INTERVAL_S}s...", flush=True)
                break
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"Runtime not READY after {READY_TIMEOUT_S}s")


def invoke_and_collect_frames(arn: str, prompt: str, session_id: str) -> list[dict]:
    """
    Invoke the AgentCore Runtime and return all SSE data frames as parsed dicts.

    The response body is an EventStream. Each chunk may contain one or more
    SSE lines. Lines prefixed with 'data: ' are parsed as JSON frames.
    """
    client = boto3.client(
        "bedrock-agentcore",
        region_name=REGION,
        endpoint_url=DATA_ENDPOINT,
    )
    payload = json.dumps({"prompt": prompt, "session_id": session_id}).encode()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=payload,
        contentType="application/json",
    )
    frames = []
    # resp["response"] is a botocore EventStream (iterable of bytes chunks)
    for chunk in resp.get("response", []):
        if isinstance(chunk, bytes):
            for line in chunk.decode("utf-8").splitlines():
                line = line.strip()
                if line.startswith("data: "):
                    frames.append(json.loads(line[len("data: "):]))
    return frames


# ── Fixtures ──────────────────────────────────────────────────────────────────


class TestAgentCoreIntegration:
    """
    Integration tests against the live deployed AgentCore Runtime.

    The agent_arn class-scoped fixture looks up the ARN once and waits for
    READY status before any test in the class runs.
    """

    @pytest.fixture(scope="class")
    def agent_arn(self):
        arn = get_agent_arn()
        wait_for_ready(arn)
        return arn

    # ── Tests ─────────────────────────────────────────────────────────────────

    def test_runtime_is_ready(self, agent_arn):
        """Sanity: the fixture itself confirms READY status before this runs."""
        assert agent_arn.startswith("arn:aws:bedrock-agentcore"), (
            f"Unexpected ARN format: {agent_arn}"
        )

    def test_streaming_response_has_text_frames(self, agent_arn):
        """
        Invoke with a simple factual prompt and validate the SSE stream.

        Asserts:
        - At least one frame received
        - Every frame has a 'text' key
        - No frame has an 'error' key
        - Concatenated text is non-empty
        """
        session_id = str(uuid.uuid4())
        frames = invoke_and_collect_frames(
            agent_arn,
            prompt="What is 2 + 2? Reply in one sentence.",
            session_id=session_id,
        )
        assert len(frames) > 0, "No SSE frames received from the agent"
        assert all("text" in f for f in frames), (
            f"At least one frame is missing the 'text' key: {frames}"
        )
        assert not any("error" in f for f in frames), (
            f"At least one error frame received: {frames}"
        )
        full_text = "".join(f["text"] for f in frames)
        assert full_text.strip(), "Concatenated response text is empty"

    def test_two_independent_sessions(self, agent_arn):
        """
        Two invocations with different session_ids must both succeed
        independently (validates session isolation).
        """
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())
        frames_a = invoke_and_collect_frames(agent_arn, "Say 'alpha'.", sid_a)
        frames_b = invoke_and_collect_frames(agent_arn, "Say 'beta'.", sid_b)
        assert len(frames_a) > 0, "Session A received no frames"
        assert len(frames_b) > 0, "Session B received no frames"
