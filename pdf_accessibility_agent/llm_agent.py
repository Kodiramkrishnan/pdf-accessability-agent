from __future__ import annotations

import json
import os
from typing import Any

import httpx

from pdf_accessibility_agent.models import RemediationPlan


SYSTEM_PROMPT = """You are a PDF accessibility remediation planner targeting PDF/UA-1 and WCAG 2.x
mappings used by validators like PAC. Output ONLY valid JSON matching this schema:
{
  "summary": "string",
  "actions": [
    {
      "action": "set_catalog",
      "params": { "language": "BCP47 tag e.g. en-US", "title": "short human title", "set_marked": true },
      "rationale": "string"
    }
  ]
}
Only use action type "set_catalog" in your JSON. Do not invent unsupported actions."""


def plan_from_openai_compatible(
    *,
    issues: list[dict[str, Any]],
    catalog: dict[str, str],
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> RemediationPlan:
    """
    Call an OpenAI-compatible chat completions API to build a RemediationPlan.

    Environment:
      OPENAI_API_KEY (or api_key argument)
      OPENAI_BASE_URL (optional, default https://api.openai.com/v1)
      OPENAI_MODEL (optional)
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set and api_key was not provided.")

    url_base = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    mdl = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    url = url_base.rstrip("/") + "/chat/completions"

    user_payload = {
        "catalog": catalog,
        "reported_issues": issues,
        "instruction": "Propose minimal catalog fixes; prefer en-US if language unknown.",
    }

    body = {
        "model": mdl,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
    }

    with httpx.Client(timeout=60) as client:
        r = client.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json=body,
        )
        r.raise_for_status()
        data = r.json()
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return RemediationPlan.model_validate(parsed)
