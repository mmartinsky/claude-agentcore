"""
agent.py — Core agent logic using the Claude Agent SDK.

Exposes a single async function `run_agent(prompt, cwd)` that runs the agent
to completion and returns the final text response.
Imported by main.py and wrapped in the BedrockAgentCoreApp entrypoint.
"""

import logging

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, UserMessage, query
import claude_agent_sdk._internal.message_parser as _mp

logger = logging.getLogger(__name__)

# Patch parse_message so unknown event types (e.g. rate_limit_event) are skipped
# instead of raising MessageParseError and killing the async generator.
_original_parse = _mp.parse_message

def _tolerant_parse(data):
    try:
        return _original_parse(data)
    except _mp.MessageParseError as e:
        if "Unknown message type" in str(e):
            logger.debug("Skipping unknown SDK event: %s", e)
            return None
        raise

_mp.parse_message = _tolerant_parse


async def run_agent(prompt: str, cwd: str = "/tmp") -> str:
    """
    Run the agent for a given prompt and return the final answer.

    Args:
        prompt: The user's instruction.
        cwd:    Working directory for tool operations (Read, Write, Bash, etc.).
                Defaults to /tmp which is always writable in the container.

    Returns:
        The agent's final text response.
    """
    options = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        # bypassPermissions is required in non-interactive (container) contexts.
        # Without it the SDK subprocess blocks waiting for a terminal confirmation
        # prompt that will never arrive.
        permission_mode="bypassPermissions",
        allowed_tools=[
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "WebSearch",
            "WebFetch",
        ],
        cwd=cwd,
        max_turns=30,
    )

    result = None
    async for message in query(prompt=prompt, options=options):
        if message is None:
            continue
        if isinstance(message, AssistantMessage):
            logger.info("AssistantMessage: %s", message)
        elif isinstance(message, UserMessage):
            logger.info("UserMessage (tool result): %s", message)
        elif isinstance(message, ResultMessage):
            result = f"[Agent error: {message.result}]" if message.is_error else (message.result or "")

    return result or "[Agent error: no result returned]"
