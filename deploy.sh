#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, push to ECR, and create/update the AgentCore Runtime.
#
# Prerequisites:
#   - AWS CLI v2 configured (aws configure / IAM role / env vars)
#   - Docker running
#   - ANTHROPIC_API_KEY exported in your shell
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# On subsequent deployments the script is fully idempotent:
#   - ECR repo creation is skipped if it already exists
#   - IAM role creation is skipped if it already exists
#   - AgentCore Runtime is updated if it already exists, created otherwise
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
AGENT_NAME="claude-agentcore-agent"
RUNTIME_NAME="claude_agentcore_agent"   # AgentCore Runtime names: [a-zA-Z][a-zA-Z0-9_]{0,47}
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_REPO_NAME="bedrock-agentcore-${AGENT_NAME}"
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ECR_URI="${ECR_REGISTRY}/${ECR_REPO_NAME}"
IMAGE_TAG="$(date -u +%Y%m%d-%H%M%S)"
IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"
IAM_ROLE_NAME="AmazonBedrockAgentCoreSDKRuntime-${REGION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROL_ENDPOINT="https://bedrock-agentcore-control.${REGION}.amazonaws.com"

echo "=== Deploying ${AGENT_NAME} ==="
echo "    Region:  ${REGION}"
echo "    Account: ${ACCOUNT_ID}"
echo ""

# ── Step 1: Create ECR repository (idempotent) ────────────────────────────────
echo "[1/6] Ensuring ECR repository exists..."
if aws ecr describe-repositories \
        --repository-names "${ECR_REPO_NAME}" \
        --region "${REGION}" \
        --output text > /dev/null 2>&1; then
    echo "      Already exists: ${ECR_URI}"
else
    aws ecr create-repository \
        --repository-name "${ECR_REPO_NAME}" \
        --region "${REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --output text > /dev/null
    echo "      Created: ${ECR_URI}"
fi

# ── Step 2: Build Docker image for linux/arm64 ────────────────────────────────
echo "[2/6] Building Docker image (linux/arm64)..."
docker build \
    --platform linux/arm64 \
    --tag "${AGENT_NAME}:${IMAGE_TAG}" \
    "${SCRIPT_DIR}"
echo "      Built: ${AGENT_NAME}:${IMAGE_TAG}"

# ── Step 3: Authenticate Docker to ECR and push ───────────────────────────────
echo "[3/6] Pushing image to ECR..."
aws ecr get-login-password --region "${REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}"
docker tag "${AGENT_NAME}:${IMAGE_TAG}" "${IMAGE_URI}"
docker push "${IMAGE_URI}"
echo "      Pushed: ${IMAGE_URI}"

# ── Step 4: Create IAM execution role (idempotent) ────────────────────────────
echo "[4/6] Ensuring IAM execution role exists..."
if ROLE_ARN="$(aws iam get-role \
        --role-name "${IAM_ROLE_NAME}" \
        --query Role.Arn \
        --output text 2>/dev/null)"; then
    echo "      Already exists: ${ROLE_ARN}"
else
    echo "      Creating IAM role ${IAM_ROLE_NAME}..."

    TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AssumeRolePolicy",
    "Effect": "Allow",
    "Principal": { "Service": "bedrock-agentcore.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "${ACCOUNT_ID}" },
      "ArnLike": {
        "aws:SourceArn": "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:*"
      }
    }
  }]
}
EOF
)

    ROLE_ARN="$(aws iam create-role \
        --role-name "${IAM_ROLE_NAME}" \
        --assume-role-policy-document "${TRUST_POLICY}" \
        --description "Execution role for Bedrock AgentCore Claude SDK agent" \
        --query Role.Arn \
        --output text)"

    EXEC_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRImageAccess",
      "Effect": "Allow",
      "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/${ECR_REPO_NAME}"
    },
    {
      "Sid": "ECRTokenAccess",
      "Effect": "Allow",
      "Action": ["ecr:GetAuthorizationToken"],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": [
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*",
        "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
      ]
    },
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:*:inference-profile/*",
        "arn:aws:bedrock:${REGION}:${ACCOUNT_ID}:*"
      ]
    }
  ]
}
EOF
)

    aws iam put-role-policy \
        --role-name "${IAM_ROLE_NAME}" \
        --policy-name "BedrockAgentCoreRuntimeExecutionPolicy" \
        --policy-document "${EXEC_POLICY}"

    echo "      Waiting 15s for IAM propagation..."
    sleep 15
    echo "      Created: ${ROLE_ARN}"
fi

# ── Step 5: Create or update AgentCore Runtime ────────────────────────────────
echo "[5/6] Creating/updating AgentCore Runtime..."

EXISTING_ID="$(python3 - <<PYEOF
import boto3, sys
client = boto3.client(
    "bedrock-agentcore-control",
    region_name="${REGION}",
    endpoint_url="${CONTROL_ENDPOINT}"
)
try:
    for r in client.list_agent_runtimes().get("agentRuntimes", []):
        if r["agentRuntimeName"] == "${RUNTIME_NAME}":
            print(r["agentRuntimeId"])
            sys.exit(0)
except Exception as e:
    print(f"", file=sys.stderr)
PYEOF
)" || true

ARTIFACT_JSON="{\"containerConfiguration\": {\"containerUri\": \"${IMAGE_URI}\"}}"

if [ -n "${EXISTING_ID:-}" ]; then
    echo "      Updating existing runtime (id: ${EXISTING_ID})..."
    CW_LOG_GROUP="/aws/bedrock-agentcore/runtimes/${EXISTING_ID}-DEFAULT"
    AGENT_ARN="$(python3 - <<PYEOF
import boto3, json
client = boto3.client(
    "bedrock-agentcore-control",
    region_name="${REGION}",
    endpoint_url="${CONTROL_ENDPOINT}"
)
resp = client.update_agent_runtime(
    agentRuntimeId="${EXISTING_ID}",
    agentRuntimeArtifact={"containerConfiguration": {"containerUri": "${IMAGE_URI}"}},
    roleArn="${ROLE_ARN}",
    environmentVariables={
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
        "CW_LOG_GROUP": "${CW_LOG_GROUP}",
    },
    networkConfiguration={"networkMode": "PUBLIC"}
)
print(resp["agentRuntimeArn"])
PYEOF
)"
else
    echo "      Creating new runtime..."
    AGENT_ARN="$(python3 - <<PYEOF
import boto3
client = boto3.client(
    "bedrock-agentcore-control",
    region_name="${REGION}",
    endpoint_url="${CONTROL_ENDPOINT}"
)
resp = client.create_agent_runtime(
    agentRuntimeName="${RUNTIME_NAME}",
    agentRuntimeArtifact={"containerConfiguration": {"containerUri": "${IMAGE_URI}"}},
    roleArn="${ROLE_ARN}",
    environmentVariables={"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"},
    networkConfiguration={"networkMode": "PUBLIC"}
)
print(resp["agentRuntimeArn"])
PYEOF
)"
fi
echo "      ARN: ${AGENT_ARN}"

# ── Step 6: Save deployment metadata ─────────────────────────────────────────
echo "[6/6] Saving deployment metadata..."
cat > "${SCRIPT_DIR}/.last_deploy.env" <<EOF
AGENT_NAME=${AGENT_NAME}
REGION=${REGION}
ACCOUNT_ID=${ACCOUNT_ID}
IMAGE_URI=${IMAGE_URI}
ROLE_ARN=${ROLE_ARN}
AGENT_ARN=${AGENT_ARN}
EOF

echo ""
echo "=== Deployment complete! ==="
echo "    Image:  ${IMAGE_URI}"
echo "    ARN:    ${AGENT_ARN}"
echo ""
echo "Run tests (waits for runtime to be READY):"
echo "    pytest tests/test_agent.py -v -s"
