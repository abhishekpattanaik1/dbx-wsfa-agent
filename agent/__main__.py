"""CLI entry point.

  python -m agent --config config.yaml                 # real workspaces + LLM
  python -m agent --config config.yaml --no-llm        # heuristics only
  python -m agent --sample --no-llm                    # fake data, no Databricks, no LLM
"""
from __future__ import annotations

import argparse
import logging

from .analyzer import analyse
from .collector import collect_all, collect_workspace
from .config import AgentCfg, LLMCfg, WorkspaceCfg, load_config
from .report import write_reports


def run(cfg: AgentCfg, sample: bool = False) -> list[dict]:
    if sample:
        from .sample_data import FakeWorkspaceClient
        contexts = collect_workspace(WorkspaceCfg(name="sample-ws"), cfg, client=FakeWorkspaceClient())
    else:
        contexts = list(collect_all(cfg))

    llm_client = None
    if cfg.llm.provider != "none" and contexts:
        from .analyzer import _client
        llm_client = _client(cfg.llm)

    results = []
    for ctx in contexts:
        logging.info("analysing %s / %s (run %s)", ctx.workspace, ctx.job_name, ctx.run_id)
        results.append({"context": ctx.to_dict(), "analysis": analyse(ctx, cfg.llm, llm_client)})
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Read-only Databricks failed-job triage agent")
    p.add_argument("--config", help="config.yaml / config.json")
    p.add_argument("--hours", type=int, help="override lookback_hours")
    p.add_argument("--no-llm", action="store_true", help="heuristics only, nothing sent to an LLM")
    p.add_argument("--sample", action="store_true", help="use built-in fake workspace data")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = load_config(a.config) if a.config else AgentCfg(workspaces=[], llm=LLMCfg())
    if a.hours:
        cfg.lookback_hours = a.hours
    if a.no_llm:
        cfg.llm.provider = "none"

    results = run(cfg, sample=a.sample)
    if not results:
        print("No failed runs in the window.")
        return
    md, js = write_reports(results, cfg.output_dir)
    print(f"{len(results)} failed job(s) analysed.\nReport: {md}\nJSON:   {js}")


if __name__ == "__main__":
    main()
