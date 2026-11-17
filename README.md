# Databricks failed-job triage agent (read-only)

Pulls failed job runs from one or more Azure Databricks workspaces, gathers the error,
stack trace, cluster termination reason and cluster events, then asks an LLM for the
likely root cause and fix. **It only recommends. It never changes jobs, clusters or code.**

```
 workspaces (config) ─► collector ─► redact + trim ─► heuristics ─► LLM ─► report (.md + .json)
   list_runs / get_run      secrets masked     known patterns   JSON:      one section per
   get_run_output           head+tail of       (OOM, quota,     root cause, failing job
   clusters.get / events    stack trace        UC perms, ...)   fix, evidence
```

## Quick start (local — the easiest way)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Try it with no Databricks and no LLM (built-in fake failures)
python -m agent --sample --no-llm

# 2. Auth to your workspaces: either ~/.databrickscfg profiles...
databricks auth login --host https://adb-xxxx.azuredatabricks.net --profile dev
#    ...or `az login` and use host + auth_type: azure-cli in the config

# 3. Configure
cp config.example.yaml config.yaml          # edit workspaces + deployment name
export AZURE_OPENAI_ENDPOINT=https://<your-aoai>.openai.azure.com/
export AZURE_OPENAI_API_KEY=...

# 4. Run
python -m agent --config config.yaml --no-llm   # first check what it collects
python -m agent --config config.yaml            # full run with LLM
python -m agent --config config.yaml --hours 72 -v
```

Output lands in `reports/failures-<timestamp>.md` (for people) and `.json` (for tooling).

Local mode only makes **outbound** calls to the Databricks REST API and Azure OpenAI, so it
works fine without any public or inbound endpoint.

## Running inside a Databricks workspace

Add this repo as a Git folder, open `notebooks/run_in_databricks.py`, put the Azure OpenAI
endpoint and key into a secret scope, and run it (or schedule it as a daily job). With no
`host`/`profile` set, it reads the current workspace using the notebook's identity.

## Keeping it read-only

The code only calls `jobs.list_runs`, `jobs.get_run`, `jobs.get_run_output`,
`clusters.get`, `clusters.events`, and the LLM has no tools. The real guarantee is
the identity: run it as a **service principal with only `CAN_VIEW`** on the jobs (and
cluster read access), not with your admin PAT.

## Data sent to the LLM

Error messages, trimmed stack traces (first 2k + last 6k chars), notebook logs, cluster
termination reasons and events. `agent/redact.py` masks Databricks tokens, `password=`/`key=`
style values, storage account keys, SAS signatures, JWTs and emails first. Use
`--no-llm` to keep everything local. Use `llm.provider: databricks` to keep everything
inside Databricks Model Serving.

## Layout

| File | What it does |
|---|---|
| `agent/collector.py` | Talks to the Databricks SDK; builds a `FailureContext` per failing job |
| `agent/redact.py` | Masks secrets, trims long logs |
| `agent/heuristics.py` | Regex catalogue of known failures, used as LLM hints and for the `--no-llm` fallback |
| `agent/analyzer.py` | Prompt + Azure OpenAI / Databricks serving call, JSON output |
| `agent/report.py` | Markdown + JSON report |
| `agent/sample_data.py` | Fake workspace for testing without Databricks |
| `notebooks/run_in_databricks.py` | Workspace-mode entry point |

## Next steps you might want

- Add your team's recurring errors to `KNOWN_PATTERNS` in `heuristics.py`.
- Post the Markdown summary to Teams/Slack, or create an Azure DevOps work item from the JSON.
- Add job config (cluster spec, libraries, DBR version) via `jobs.get(job_id)` for richer context.
- Compare with the last successful run of the same job (duration, cluster size) to spot regressions.
