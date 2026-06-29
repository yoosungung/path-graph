from __future__ import annotations

import re
import time
from typing import Any

import httpx

from path_graph.config import Settings, get_settings
from path_graph.contracts.schemas import AgentInvokeInput, AgentInvokePayload


class AgentInvokeError(RuntimeError):
    pass


def invoke_agent(
    agent: str,
    inp: AgentInvokeInput,
    session_id: str,
    *,
    settings: Settings | None = None,
    timeout: float = 600.0,
    max_retries: int = 5,
) -> dict[str, Any]:
    s = settings or get_settings()
    token = s.pipeline_agent_access_token
    if not token:
        raise AgentInvokeError("PIPELINE_AGENT_ACCESS_TOKEN not set")

    payload = AgentInvokePayload.from_input(agent, inp, session_id)
    url = f"{s.envoy_url.rstrip('/')}/v1/agents/invoke"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload.model_dump(), headers=headers)
                if resp.status_code in (429, 503):
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, dict) and "output" in body:
                    return body["output"]
                return body
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise AgentInvokeError(str(exc)) from exc
    raise AgentInvokeError("max retries exceeded")


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(text: str) -> list[str]:
    return list(dict.fromkeys(WIKILINK_RE.findall(text)))
