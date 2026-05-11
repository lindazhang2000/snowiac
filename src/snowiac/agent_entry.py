"""Microsoft Agent Framework HTTP entry point.

Wraps the IntakeAgent with the Foundry hosting adapter so this app can be
deployed as a Microsoft Foundry hosted agent. The full FastAPI app
(``snowiac.server``) is the recommended entry point because it also handles
the GitHub-merge webhook; this module is provided for Foundry deployments
that only need the conversational intake surface.
"""
from __future__ import annotations

import asyncio

from agent_framework import Agent
from azure.ai.agentserver.agentframework import from_agent_framework

from .agents.intake import INSTRUCTIONS
from .llm import get_chat_client


async def main() -> None:
    client = get_chat_client()
    async with Agent(
        client=client, name="SnowIaCIntakeAgent", instructions=INSTRUCTIONS
    ) as agent:
        await from_agent_framework(agent).run_async()


if __name__ == "__main__":
    asyncio.run(main())
