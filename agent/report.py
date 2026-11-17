"""Write a Markdown report (for humans) and a JSON file (for tooling / later ticketing)."""
from __future__ import annotations

import json
import time
from pathlib import Path


def _bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def write_reports(results: list[dict], output_dir: str) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = out / f"failures-{stamp}.json"
    md_path = out / f"failures-{stamp}.md"

    json_path.write_text(json.dumps(results, indent=2, default=str))

    lines = [f"# Databricks failed-job triage — {time.strftime('%Y-%m-%d %H:%M')}",
             "", "_Recommendations only. Nothing was changed by this agent._", "",
             "| Workspace | Job | Failures | Category | Owner | Confidence | Transient |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        c, a = r["context"], r["analysis"]
        lines.append(f"| {c['workspace']} | [{c['job_name']}]({c['run_url']}) | {c['failures_in_window']} | "
                     f"{a.get('category','')} | {a.get('owner','')} | {a.get('confidence','')} | "
                     f"{a.get('transient','')} |")

    for r in results:
        c, a = r["context"], r["analysis"]
        tasks = ", ".join(f"{t['task_key']} ({t['result_state']})" for t in c["failed_tasks"]) or "-"
        lines += [
            "", "---", f"## {c['workspace']} / {c['job_name']}",
            f"Run: [{c['run_id']}]({c['run_url']}) at {c['start_time']} · state `{c['result_state']}` · "
            f"failed tasks: {tasks} · source: {a.get('source')}",
            "", f"**Root cause:** {a.get('root_cause','')}",
            "", "**Evidence**", _bullets(a.get("evidence")),
            "", "**Recommended fix**", _bullets(a.get("recommended_fix")),
        ]
        if a.get("prevention"):
            lines += ["", "**Prevention**", _bullets(a["prevention"])]
        if a.get("next_checks"):
            lines += ["", "**If that doesn't work, check**", _bullets(a["next_checks"])]

    md_path.write_text("\n".join(lines) + "\n")
    return md_path, json_path
