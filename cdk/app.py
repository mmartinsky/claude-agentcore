#!/usr/bin/env python3
import aws_cdk as cdk
from stack import AgentCoreStack

app = cdk.App()
AgentCoreStack(app, "AgentCoreStack", env=cdk.Environment(region="us-east-1"))
app.synth()
