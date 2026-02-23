# Claude Agent Instructions

## Memory

After any session where you learn something durable about this project — a fix,
a gotcha, a pattern, a deployment detail — update the memory files:

- `~/.claude/projects/-Users-mike-claude-agentcore/memory/MEMORY.md` — high-level index (keep under 200 lines)
- `~/.claude/projects/-Users-mike-claude-agentcore/memory/bedrock-agentcore.md` — AWS/deployment details

Things worth capturing: AWS API behaviour, IAM quirks, SDK gotchas, deployment
steps that aren't obvious from the code, things that broke and why.

## Project Overview

Bedrock AgentCore runtime wrapping the Claude Agent SDK. Each invocation runs a
full agent turn and streams the result back as SSE.

- `main.py` — BedrockAgentCoreApp entrypoint
- `agent.py` — calls `query()` from `claude_agent_sdk`
- `deploy.sh` — builds arm64 Docker image, pushes to ECR, updates the runtime
- `.github/workflows/deploy.yml` — CI/CD: runs local tests then calls `deploy.sh`

## Deploy

Push to `main` to deploy via GitHub Actions (preferred).

To deploy locally:
```bash
source ~/.zshrc   # loads ANTHROPIC_API_KEY
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" bash deploy.sh
```

## Test

```bash
# Local unit tests (no AWS needed, uses ANTHROPIC_API_KEY directly):
pytest tests/test_agent_local.py -v -s

# Integration tests against the live deployed runtime:
pytest tests/test_agent.py -v -s
```

## Key facts

- Runtime ID: `claude_agentcore_agent-g43zdcBhfT` in `us-east-1`
- Container must listen on port 8080 and respond to `GET /ping`
- Use `query()` not `ClaudeSDKClient` — one-shot, stateless, simpler
- Log to `sys.stdout` — AgentCore captures stdout for CloudWatch, not stderr
- `PYTHONUNBUFFERED=1` is set in the Dockerfile
