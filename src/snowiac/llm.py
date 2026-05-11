"""Shared FoundryChatClient instance.

Per Agent Framework best practices: one client can be reused across agents.
"""
from __future__ import annotations

from functools import lru_cache

from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from .config import get_settings


@lru_cache
def get_chat_client() -> FoundryChatClient:
    s = get_settings()
    return FoundryChatClient(
        project_endpoint=s.foundry_project_endpoint,
        model=s.foundry_model_deployment_name,
        credential=DefaultAzureCredential(),
    )
