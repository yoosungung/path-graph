"""Parse JSON objects from LLM text responses."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def normalize_llm_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    match = _FENCE_RE.search(raw)
    if match:
        raw = match.group(1).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


async def invoke_json_llm(
    llm: Any,
    prompt: str,
    *,
    response_format: dict,
    max_tokens: int | None = None,
) -> dict:
    from langchain_core.messages import HumanMessage

    bind_kwargs: dict[str, Any] = {"response_format": response_format}
    if max_tokens is not None:
        bind_kwargs["max_tokens"] = max_tokens
    bound = llm.bind(**bind_kwargs)

    last_exc: Exception | None = None
    for attempt in range(2):
        response = await bound.ainvoke([HumanMessage(content=prompt)])
        content = normalize_llm_text(
            response.content if hasattr(response, "content") else response
        )
        try:
            return parse_json_object(content)
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt == 0 and not content.strip():
                continue
            raise
    assert last_exc is not None
    raise last_exc
