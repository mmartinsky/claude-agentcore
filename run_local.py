#!/usr/bin/env python3
"""run_local.py — Run the agent locally without Docker or AWS."""

import asyncio
import sys

from agent import run_agent

prompt = " ".join(sys.argv[1:]) or "What is 2+2?"


async def main():
    await run_agent(prompt, cwd="/tmp")


asyncio.run(main())
