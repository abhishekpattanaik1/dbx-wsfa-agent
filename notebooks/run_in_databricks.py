# Databricks notebook source
# MAGIC %md
# MAGIC # Failed-job triage agent (workspace mode)
# MAGIC Import this repo as a Git folder, then run this notebook (or schedule it as a job).
# MAGIC With no host/profile set, the current workspace is analysed using the notebook's own identity.
# MAGIC For other workspaces, add them in the config with `host` + `auth_type: azure-client-secret`
# MAGIC and set the service principal env vars from a secret scope (cell below).

# COMMAND ----------
# MAGIC %pip install -q databricks-sdk openai pyyaml
# MAGIC %restart_python

# COMMAND ----------
import os, sys

repo_root = os.path.dirname(os.getcwd())          # notebooks/ -> repo root
sys.path.insert(0, repo_root)

# LLM credentials from a secret scope (create it once: `databricks secrets create-scope triage-agent`)
os.environ["AZURE_OPENAI_ENDPOINT"] = dbutils.secrets.get("triage-agent", "aoai-endpoint")
os.environ["AZURE_OPENAI_API_KEY"] = dbutils.secrets.get("triage-agent", "aoai-key")

# Optional: service principal for cross-workspace reads
# os.environ["ARM_TENANT_ID"]     = dbutils.secrets.get("triage-agent", "sp-tenant-id")
# os.environ["ARM_CLIENT_ID"]     = dbutils.secrets.get("triage-agent", "sp-client-id")
# os.environ["ARM_CLIENT_SECRET"] = dbutils.secrets.get("triage-agent", "sp-client-secret")

# COMMAND ----------
from agent.config import AgentCfg, LLMCfg, WorkspaceCfg
from agent.__main__ import run
from agent.report import write_reports

cfg = AgentCfg(
    workspaces=[WorkspaceCfg(name="this-workspace")],   # no host => current workspace
    lookback_hours=24,
    llm=LLMCfg(provider="azure_openai", deployment="gpt-4o"),
    output_dir="/tmp/triage-reports",
)
results = run(cfg)
print(f"{len(results)} failed job(s) analysed")

# COMMAND ----------
if results:
    md_path, json_path = write_reports(results, cfg.output_dir)
    displayHTML(f"<pre>{open(md_path).read()}</pre>")
