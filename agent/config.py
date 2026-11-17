"""Config loading. Supports YAML (needs pyyaml) or JSON."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceCfg:
    name: str
    profile: str | None = None      # profile in ~/.databrickscfg
    host: str | None = None         # or host + unified auth (env vars / az cli)
    auth_type: str | None = None    # e.g. "azure-cli", "azure-client-secret", "pat"
    job_name_contains: list[str] = field(default_factory=list)  # optional filter


@dataclass
class LLMCfg:
    provider: str = "azure_openai"  # azure_openai | databricks | none
    deployment: str | None = None   # Azure deployment name / Databricks serving endpoint name
    api_version: str = "2024-10-21"
    temperature: float = 0.1
    max_output_tokens: int = 1200


@dataclass
class AgentCfg:
    workspaces: list[WorkspaceCfg]
    lookback_hours: int = 24
    max_runs_per_workspace: int = 200
    failure_states: list[str] = field(
        default_factory=lambda: ["FAILED", "TIMEDOUT", "INTERNAL_ERROR"]
    )
    latest_failure_per_job_only: bool = True  # analyse one run per job, report the count
    include_cluster_events: bool = True
    log_head_chars: int = 2000
    log_tail_chars: int = 6000
    output_dir: str = "reports"
    llm: LLMCfg = field(default_factory=LLMCfg)


def load_config(path: str) -> AgentCfg:
    text = Path(path).read_text()
    if path.endswith((".yaml", ".yml")):
        import yaml  # lazy: only needed for YAML configs
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)

    workspaces = [WorkspaceCfg(**w) for w in raw.pop("workspaces", [])]
    llm = LLMCfg(**raw.pop("llm", {}))
    if not llm.deployment:
        llm.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("LLM_DEPLOYMENT")
    return AgentCfg(workspaces=workspaces, llm=llm, **raw)
