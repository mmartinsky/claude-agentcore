# claude-agentcore

A [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk) agent running on [AWS Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html). Each invocation runs a full agent turn with tools (Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch) and streams the result back as SSE.

## How it works

```
Caller → AgentCore Runtime → main.py (BedrockAgentCoreApp)
                                   → agent.py (Claude SDK query())
                                   ← SSE stream
```

`main.py` wraps the agent in a `BedrockAgentCoreApp` entrypoint. Because the handler is an async generator, AgentCore automatically streams output as `text/event-stream`, avoiding gateway timeouts on long agent runs.

`agent.py` calls `query()` from the Claude Agent SDK — one-shot, stateless, no session management overhead.

## Invoke

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-id claude_agentcore_agent-znXwxnEJ9p \
  --region us-east-1 \
  --payload '{"prompt": "what is 2+2"}'
```

Payload fields:

| Field | Required | Description |
|-------|----------|-------------|
| `prompt` | yes | The instruction for the agent |
| `session_id` | no | Isolates the working directory under `/tmp` for concurrent invocations |

## Deploy

Push to `main` — GitHub Actions runs local tests then calls `deploy.sh`.

To deploy locally:

```bash
source ~/.zshrc          # loads ANTHROPIC_API_KEY
./deploy.sh
```

First-time setup requires bootstrapping CDK once:

```bash
cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1
```

### How deploy works

`deploy.sh` runs `cdk deploy` on the CDK stack in `cdk/`. CDK handles everything:

1. Builds the `linux/arm64` Docker image and pushes it to ECR
2. Creates/updates the IAM execution role
3. Creates/updates the `AWS::BedrockAgentCore::Runtime` CloudFormation resource

## Test

```bash
# Unit tests (no AWS needed):
pytest tests/test_agent_local.py -v -s

# Integration tests against the live runtime:
pytest tests/test_agent.py -v -s
```

## Project layout

```
├── main.py              # BedrockAgentCoreApp entrypoint
├── agent.py             # Claude SDK query() wrapper
├── Dockerfile           # linux/arm64 container
├── requirements.txt     # Python deps
├── deploy.sh            # Local deploy: cdk deploy
├── cdk/
│   ├── app.py           # CDK app entry point
│   ├── stack.py         # Stack: DockerImageAsset + Runtime + IAM role
│   └── requirements.txt # CDK Python deps
└── tests/
    ├── test_agent_local.py  # Unit tests
    └── test_agent.py        # Integration tests
```

## Configuration

`ANTHROPIC_API_KEY` is read from the environment at deploy time and passed to the runtime as an environment variable. It must be exported before running `deploy.sh` or set as a GitHub Actions secret (`ANTHROPIC_API_KEY`).

AWS credentials for GitHub Actions use OIDC — set `AWS_ROLE_ARN` as a secret with a role that has permissions to deploy CloudFormation, ECR, and IAM.
