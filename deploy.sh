#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, push, and deploy the AgentCore Runtime via CDK.
#
# Prerequisites:
#   - Node.js + aws-cdk CLI  (npm install -g aws-cdk)
#   - AWS CLI v2 configured
#   - Docker running
#   - ANTHROPIC_API_KEY exported
#   - CDK bootstrapped once:  cdk bootstrap aws://ACCOUNT/us-east-1
#
# Usage:
#   source ~/.zshrc   # loads ANTHROPIC_API_KEY
#   ./deploy.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Deploying claude_agentcore_agent via CDK ==="
echo ""

pip install -q -r "${SCRIPT_DIR}/cdk/requirements.txt"

npx --yes aws-cdk deploy AgentCoreStack \
    --app "python3 ${SCRIPT_DIR}/cdk/app.py" \
    --outputs-file "${SCRIPT_DIR}/cdk-outputs.json" \
    --require-approval never

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Run tests (waits for runtime to be READY):"
echo "    pytest tests/test_agent.py -v -s"
