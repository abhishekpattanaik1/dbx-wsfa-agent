"""LLM analysis. Produces recommendations only — it has no tools and cannot act."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict

from .collector import FailureContext
from .config import LLMCfg
from .heuristics import classify, evidence_lines

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior Databricks platform engineer doing failure triage on Azure Databricks.
You get the details of one failed job run: run/task state, error, stack trace (trimmed), cluster
termination reason and cluster events, plus pattern-match hints.

Rules:
- Base every conclusion on the evidence given. Quote the exact log line that supports it.
- If the evidence is not enough, say so and list what to check next. Do not invent config values.
- Distinguish platform/infra causes (capacity, network, init scripts, permissions) from code/data causes.
- You only recommend. Never claim anything was changed.

Return ONLY a JSON object with these keys:
{
  "category": "short label, e.g. memory | cluster_launch_capacity | dependency | permissions | data_or_schema | code_bug | delta_concurrency | timeout | transient_network | other",
  "owner": "platform | job_owner | unclear",
  "root_cause": "1-3 sentences",
  "evidence": ["exact log lines that support the root cause"],
  "confidence": "high | medium | low",
  "transient": true/false,
  "recommended_fix": ["ordered, concrete steps"],
  "prevention": ["optional longer-term changes, e.g. retries, pools, alerts"],
  "next_checks": ["what to look at if the fix does not work or confidence is low"]
}"""


def build_user_prompt(ctx: FailureContext) -> str:
    hints = classify(ctx.evidence_text())
    payload = {
        "workspace": ctx.workspace,
        "job_name": ctx.job_name,
        "run_state": ctx.result_state,
        "run_state_message": ctx.state_message,
        "run_termination": ctx.termination,
        "failures_of_this_job_in_window": ctx.failures_in_window,
        "failed_tasks": [
            {k: v for k, v in asdict(t).items() if v not in ("", None, [])}
            for t in ctx.failed_tasks
        ],
        "pattern_hints": [asdict(h) for h in hints],
    }
    return "Analyse this failed Databricks job run:\n\n" + json.dumps(payload, indent=2, default=str)


def _client(cfg: LLMCfg):
    from openai import AzureOpenAI, OpenAI  # lazy import

    if cfg.provider == "azure_openai":
        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=cfg.api_version,
        )
    if cfg.provider == "databricks":
        # Databricks Model Serving / Foundation Model APIs are OpenAI-compatible.
        host = os.environ["DATABRICKS_HOST"].rstrip("/")
        return OpenAI(base_url=f"{host}/serving-endpoints", api_key=os.environ["DATABRICKS_TOKEN"])
    raise ValueError(f"Unknown LLM provider {cfg.provider}")


def heuristic_only(ctx: FailureContext) -> dict:
    hints = classify(ctx.evidence_text())
    if not hints:
        return {"category": "unknown", "owner": "unclear", "confidence": "low",
                "root_cause": "No known pattern matched. Needs LLM or manual review.",
                "recommended_fix": [], "evidence": [], "transient": False, "source": "heuristics"}
    h = hints[0]
    return {"category": h.category, "owner": "unclear", "confidence": "low",
            "root_cause": h.signal, "recommended_fix": [h.typical_fix],
            "other_signals": [x.signal for x in hints[1:]],
            "evidence": evidence_lines(ctx.evidence_text(), h.category),"transient": h.transient, "source": "heuristics"}


def analyse(ctx: FailureContext, cfg: LLMCfg, client=None) -> dict:
    if cfg.provider == "none":
        return heuristic_only(ctx)
    client = client or _client(cfg)
    try:
        resp = client.chat.completions.create(
            model=cfg.deployment,
            temperature=cfg.temperature,
            max_tokens=cfg.max_output_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(ctx)},
            ],
        )
        result = json.loads(resp.choices[0].message.content)
        result["source"] = "llm"
        return result
    except Exception as e:
        log.warning("LLM analysis failed for run %s (%s); falling back to heuristics", ctx.run_id, e)
        fallback = heuristic_only(ctx)
        fallback["llm_error"] = str(e)
        return fallback
