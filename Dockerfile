# =============================================================================
# AWS Bedrock AgentCore requires linux/arm64 containers.
# Build with:
#   docker build --platform linux/arm64 -t claude-agentcore-agent:latest .
#
# On Apple Silicon (M1/M2/M3) this builds natively.
# On x86 hosts you need Docker BuildKit with QEMU emulation:
#   docker buildx create --use
#   docker buildx build --platform linux/arm64 --load -t claude-agentcore-agent:latest .
# =============================================================================
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /app

ENV DOCKER_CONTAINER=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1

# Install Python dependencies first so this layer is cached until
# requirements.txt changes.
#
# IMPORTANT: claude-agent-sdk is installed here (inside the container) rather
# than copied from the host. The PyPI wheel is platform-specific — the macOS
# ARM64 wheel ships a macOS binary that will not execute on Linux. Installing
# inside the Linux container causes pip to download the correct Linux wheel.
COPY requirements.txt .
RUN uv pip install -r requirements.txt

# Create a non-root user — security best practice and matches the AgentCore
# starter toolkit container template.
RUN useradd -m -u 1000 agentuser
USER agentuser

# AgentCore requires the container to listen on port 8080 and respond to
# GET /ping with a healthy status.
EXPOSE 8080

# Copy application source last (changes most frequently — worst cache layer).
COPY --chown=agentuser:agentuser agent.py main.py ./

# ANTHROPIC_API_KEY must NOT be baked into the image.
# Pass it at runtime via:
#   docker run -e ANTHROPIC_API_KEY=... ...
# or via AgentCore Runtime environmentVariables at create/update time.

CMD ["python", "main.py"]
