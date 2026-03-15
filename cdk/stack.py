import os
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import aws_bedrock_agentcore_alpha as agentcore
from constructs import Construct


class AgentCoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Build and push the agent image (linux/arm64) to CDK-managed ECR
        image = ecr_assets.DockerImageAsset(
            self,
            "AgentImage",
            directory=str(Path(__file__).parent.parent),
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # AgentCore Runtime — CDK manages the IAM role and CloudFormation resource
        runtime = agentcore.Runtime(
            self,
            "AgentRuntime",
            runtime_name="claude_agentcore_agent",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_image_uri(
                image.image_uri
            ),
            environment_variables={
                "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            },
            network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
        )

        # Grant the auto-created execution role permission to pull the image
        image.repository.grant_pull(runtime.role)

        CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)
        CfnOutput(self, "RuntimeId", value=runtime.agent_runtime_id)
        CfnOutput(self, "ImageUri", value=image.image_uri)
