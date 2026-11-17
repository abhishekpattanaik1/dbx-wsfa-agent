"""Pull failed job runs + error details from one or more workspaces.

READ-ONLY: this module only calls list/get endpoints:
  jobs.list_runs, jobs.get_run, jobs.get_run_output, clusters.get, clusters.events
Run it as a principal that has only CAN_VIEW on jobs and clusters. That
permission, not this code, is the real guarantee that nothing gets changed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .config import AgentCfg, WorkspaceCfg
from .redact import head_tail, redact

log = logging.getLogger(__name__)


@dataclass
class TaskFailure:
    task_key: str
    task_run_id: int
    result_state: str
    state_message: str = ""
    error: str = ""
    error_trace: str = ""
    logs: str = ""
    cluster_id: str | None = None
    cluster_termination: str = ""
    cluster_events: list[str] = field(default_factory=list)
    attempt_number: int = 0


@dataclass
class FailureContext:
    workspace: str
    job_id: int
    job_name: str
    run_id: int
    run_url: str
    start_time: str
    result_state: str
    state_message: str
    termination: str
    failures_in_window: int = 1
    failed_tasks: list[TaskFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evidence_text(self) -> str:
        """All the text the heuristics and the LLM look at."""
        parts = [self.state_message, self.termination]
        for t in self.failed_tasks:
            parts += [t.state_message, t.error, t.error_trace, t.logs,
                      t.cluster_termination, *t.cluster_events]
        return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- helpers

def _val(obj: Any, *path: str, default: Any = "") -> Any:
    """Safe nested getattr that also unwraps SDK enums to their string value."""
    for p in path:
        if obj is None:
            return default
        obj = getattr(obj, p, None)
    if obj is None:
        return default
    return getattr(obj, "value", obj)


def _ms_to_iso(ms: int | None) -> str:
    if not ms:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ms / 1000))


def make_client(ws: WorkspaceCfg):
    from databricks.sdk import WorkspaceClient  # lazy import

    kwargs: dict[str, Any] = {}
    if ws.profile:
        kwargs["profile"] = ws.profile
    if ws.host:
        kwargs["host"] = ws.host
    if ws.auth_type:
        kwargs["auth_type"] = ws.auth_type
    # No kwargs at all == inside a Databricks notebook/job: picks up runtime auth.
    return WorkspaceClient(**kwargs)


def _run_state(run) -> tuple[str, str, str]:
    """Return (result_state, state_message, termination) across old & new API fields."""
    result = _val(run, "state", "result_state") or _val(run, "state", "life_cycle_state")
    msg = _val(run, "state", "state_message")
    term_code = _val(run, "status", "termination_details", "code")
    term_type = _val(run, "status", "termination_details", "type")
    term_msg = _val(run, "status", "termination_details", "message")
    termination = " | ".join(str(x) for x in (term_type, term_code, term_msg) if x)
    return str(result), str(msg), termination


# ---------------------------------------------------------------- collection

def _cluster_details(w, cluster_id: str, include_events: bool) -> tuple[str, list[str]]:
    termination, events = "", []
    try:
        c = w.clusters.get(cluster_id)
        code = _val(c, "termination_reason", "code")
        ctype = _val(c, "termination_reason", "type")
        params = getattr(getattr(c, "termination_reason", None), "parameters", None) or {}
        termination = f"{ctype} {code} {params}".strip() if code else str(_val(c, "state_message"))
    except Exception as e:  # cluster may be gone (job clusters are purged after ~30 days)
        termination = f"(cluster details unavailable: {e.__class__.__name__})"

    if include_events:
        try:
            try:
                from databricks.sdk.service.compute import GetEventsOrder
                order_kw = {"order": GetEventsOrder.DESC}
            except ImportError:  # sample mode without the SDK installed
                order_kw = {}
            for i, ev in enumerate(w.clusters.events(cluster_id=cluster_id, limit=15, **order_kw)):
                if i >= 15:
                    break
                details = getattr(ev, "details", None)
                reason = _val(details, "reason", "code") if details else ""
                cause = _val(details, "cause") if details else ""
                events.append(f"{_ms_to_iso(ev.timestamp)} {_val(ev, 'type')} {reason} {cause}".strip())
        except Exception as e:
            events.append(f"(cluster events unavailable: {e.__class__.__name__})")
    return termination, events


def _task_failure(w, cfg: AgentCfg, task) -> TaskFailure:
    state, msg, _ = _run_state(task)
    tf = TaskFailure(
        task_key=task.task_key,
        task_run_id=task.run_id,
        result_state=state,
        state_message=redact(msg),
        attempt_number=task.attempt_number or 0,
        cluster_id=_val(task, "cluster_instance", "cluster_id") or task.existing_cluster_id or None,
    )
    try:
        out = w.jobs.get_run_output(run_id=task.run_id)
        tf.error = redact(out.error or "")
        tf.error_trace = redact(head_tail(out.error_trace or "", cfg.log_head_chars, cfg.log_tail_chars))
        tf.logs = redact(head_tail(out.logs or "", 1000, 3000))
    except Exception as e:
        tf.error = f"(run output unavailable: {e})"

    if tf.cluster_id:
        tf.cluster_termination, tf.cluster_events = _cluster_details(
            w, tf.cluster_id, cfg.include_cluster_events)
    return tf


def _is_failure(run, cfg: AgentCfg) -> bool:
    result = _val(run, "state", "result_state")
    life = _val(run, "state", "life_cycle_state")
    return result in cfg.failure_states or life in cfg.failure_states


def collect_workspace(ws: WorkspaceCfg, cfg: AgentCfg, client=None) -> list[FailureContext]:
    w = client or make_client(ws)
    since_ms = int((time.time() - cfg.lookback_hours * 3600) * 1000)

    failed_runs, scanned = [], 0
    for run in w.jobs.list_runs(completed_only=True, start_time_from=since_ms):
        scanned += 1
        if scanned > cfg.max_runs_per_workspace:
            break
        if not _is_failure(run, cfg):
            continue
        name = run.run_name or ""
        if ws.job_name_contains and not any(s.lower() in name.lower() for s in ws.job_name_contains):
            continue
        failed_runs.append(run)
    log.info("[%s] scanned %d runs, %d failed", ws.name, scanned, len(failed_runs))

    # Optionally keep only the newest failed run per job (list_runs returns newest first)
    counts: dict[int, int] = {}
    for r in failed_runs:
        counts[r.job_id] = counts.get(r.job_id, 0) + 1
    if cfg.latest_failure_per_job_only:
        seen: set[int] = set()
        failed_runs = [r for r in failed_runs if not (r.job_id in seen or seen.add(r.job_id))]

    results = []
    for r in failed_runs:
        run = w.jobs.get_run(run_id=r.run_id)
        state, msg, term = _run_state(run)
        ctx = FailureContext(
            workspace=ws.name, job_id=run.job_id, job_name=run.run_name or str(run.job_id),
            run_id=run.run_id, run_url=run.run_page_url or "", start_time=_ms_to_iso(run.start_time),
            result_state=state, state_message=redact(msg), termination=redact(term),
            failures_in_window=counts.get(run.job_id, 1),
        )
        for task in run.tasks or []:
            if _is_failure(task, cfg):
                ctx.failed_tasks.append(_task_failure(w, cfg, task))
        results.append(ctx)
    return results


def collect_all(cfg: AgentCfg) -> Iterable[FailureContext]:
    for ws in cfg.workspaces:
        try:
            yield from collect_workspace(ws, cfg)
        except Exception as e:
            log.error("[%s] collection failed: %s", ws.name, e)
