from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

import httpx

from path_graph.config import Settings, get_settings
from path_graph.contracts.schemas import (
    AgentInvokeInput,
    AgentInvokePayload,
    unwrap_agent_graph_output,
)


class AgentInvokeError(RuntimeError):
    pass


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(text: str) -> list[str]:
    return list(dict.fromkeys(WIKILINK_RE.findall(text)))


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _unwrap_output(body: dict[str, Any]) -> dict[str, Any]:
    return unwrap_agent_graph_output(body)


def _argo_callback(job_id: str, settings: Settings) -> dict[str, Any] | None:
    namespace = settings.argo_workflow_namespace or os.environ.get("ARGO_WORKFLOW_NAMESPACE", "")
    workflow = settings.argo_workflow_name or os.environ.get("ARGO_WORKFLOW_NAME", "")
    if not namespace or not workflow:
        return None
    return {
        "argo": {
            "namespace": namespace,
            "workflow": workflow,
            "node_field_selector": f"inputs.parameters.job-id.value={job_id}",
        }
    }


def _invoke_sync(
    agent: str,
    payload: AgentInvokePayload,
    *,
    settings: Settings,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    url = f"{settings.envoy_url.rstrip('/')}/v1/agents/invoke"
    headers = _auth_headers(settings.pipeline_agent_access_token)
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
                return _unwrap_output(resp.json())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise AgentInvokeError(str(exc)) from exc
    raise AgentInvokeError("max retries exceeded")


def _submit_async_job(
    agent: str,
    payload: AgentInvokePayload,
    *,
    settings: Settings,
    max_retries: int,
) -> str:
    url = f"{settings.envoy_url.rstrip('/')}/v1/agents/jobs"
    headers = _auth_headers(settings.pipeline_agent_access_token)
    job_id = str(uuid.uuid4())
    body = payload.model_dump()
    body["job_id"] = job_id
    callback = _argo_callback(job_id, settings)
    if callback and settings.pipeline_agent_invoke_mode == "async_suspend":
        body["callback"] = callback

    delay = 1.0
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=body, headers=headers)
                if resp.status_code in (429, 503):
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("job_id") or job_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503) and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise AgentInvokeError(str(exc)) from exc
    raise AgentInvokeError("max retries exceeded")


def _poll_async_job(
    agent: str,
    job_id: str,
    *,
    settings: Settings,
) -> dict[str, Any]:
    url = (
        f"{settings.envoy_url.rstrip('/')}/v1/agents/jobs/{job_id}"
        f"?agent={agent}"
    )
    headers = _auth_headers(settings.pipeline_agent_access_token)
    deadline = time.monotonic() + settings.pipeline_agent_job_max_wait_s
    interval = max(0.0, settings.pipeline_agent_job_poll_interval_s)

    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output")
                if output is None:
                    raise AgentInvokeError(f"job {job_id} succeeded without output")
                if isinstance(output, dict):
                    return _unwrap_output(output)
                return unwrap_agent_graph_output(json.loads(json.dumps(output)))
            if status == "failed":
                raise AgentInvokeError(data.get("error") or f"job {job_id} failed")
            if interval:
                time.sleep(interval)
    raise AgentInvokeError(
        f"job {job_id} timed out after {settings.pipeline_agent_job_max_wait_s}s"
    )


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
    mode = s.pipeline_agent_invoke_mode.strip().lower()
    if mode == "sync":
        return _invoke_sync(agent, payload, settings=s, timeout=timeout, max_retries=max_retries)

    job_id = _submit_async_job(agent, payload, settings=s, max_retries=max_retries)
    if mode == "async_suspend":
        raise AgentInvokeError(
            "async_suspend requires Argo suspend step — use async_poll in monolithic graphrag step"
        )
    return _poll_async_job(agent, job_id, settings=s)
