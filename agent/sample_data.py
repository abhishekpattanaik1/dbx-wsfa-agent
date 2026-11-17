"""A fake WorkspaceClient with canned failures, so you can try the pipeline
(and tweak prompts/heuristics) without touching a real workspace."""
from __future__ import annotations

import time
from types import SimpleNamespace as NS


def _enum(v):
    return NS(value=v)


def _state(result, msg="", life="TERMINATED"):
    return NS(result_state=_enum(result), life_cycle_state=_enum(life), state_message=msg)


NOW = int(time.time() * 1000)

_RUNS = {
    101: NS(job_id=1, run_id=101, run_name="daily_sales_agg", start_time=NOW - 3_600_000,
            run_page_url="https://adb-111.azuredatabricks.net/#job/1/run/101",
            state=_state("FAILED", "Task ingest failed"), status=None,
            tasks=[NS(task_key="ingest", run_id=1011, attempt_number=0, existing_cluster_id=None,
                      cluster_instance=NS(cluster_id="0101-jobcluster"),
                      state=_state("FAILED", "Workload failed"), status=None)]),
    102: NS(job_id=2, run_id=102, run_name="customer_scd2_merge", start_time=NOW - 7_200_000,
            run_page_url="https://adb-111.azuredatabricks.net/#job/2/run/102",
            state=_state("FAILED", "Cluster failed to launch"), status=None,
            tasks=[NS(task_key="merge", run_id=1021, attempt_number=1, existing_cluster_id=None,
                      cluster_instance=NS(cluster_id="0102-jobcluster"),
                      state=_state("FAILED", "Cluster 0102-jobcluster was terminated"), status=None)]),
    103: NS(job_id=2, run_id=103, run_name="customer_scd2_merge", start_time=NOW - 9_000_000,
            run_page_url="https://adb-111.azuredatabricks.net/#job/2/run/103",
            state=_state("FAILED", "Cluster failed to launch"), status=None, tasks=[]),
    104: NS(job_id=3, run_id=104, run_name="ok_job", start_time=NOW - 1_000_000,
            run_page_url="", state=_state("SUCCESS"), status=None, tasks=[]),
}

_OUTPUTS = {
    1011: NS(error="Py4JJavaError: An error occurred while calling o412.collectToPython.",
             error_trace=("org.apache.spark.SparkException: Job aborted due to stage failure: Total size of "
                          "serialized results of 212 tasks (4.1 GiB) is bigger than spark.driver.maxResultSize "
                          "(4.0 GiB)\n  at org.apache.spark.scheduler.DAGScheduler...\n"
                          "File \"/Workspace/Repos/sales/ingest.py\", line 88, in <module>\n"
                          "    pdf = df.toPandas()\n"
                          "storage key: AccountKey=abc123SECRET=="),
             logs=""),
    1021: NS(error="", error_trace="", logs=""),
}

_CLUSTERS = {
    "0101-jobcluster": NS(state_message="", termination_reason=NS(code=_enum("JOB_FINISHED"),
                                                                  type=_enum("SUCCESS"), parameters={})),
    "0102-jobcluster": NS(state_message="", termination_reason=NS(
        code=_enum("CLOUD_PROVIDER_LAUNCH_FAILURE"), type=_enum("CLOUD_FAILURE"),
        parameters={"azure_error_code": "QuotaExceeded",
                    "azure_error_message": "Operation could not be completed as it results in exceeding "
                                           "approved standardEDSv4Family Cores quota. Region: westeurope."})),
}


class _Jobs:
    def list_runs(self, completed_only=True, start_time_from=0, **_):
        return [r for r in _RUNS.values() if r.start_time >= start_time_from]

    def get_run(self, run_id):
        return _RUNS[run_id]

    def get_run_output(self, run_id):
        return _OUTPUTS[run_id]


class _Clusters:
    def get(self, cluster_id):
        return _CLUSTERS[cluster_id]

    def events(self, cluster_id, **_):
        if cluster_id == "0102-jobcluster":
            return [NS(timestamp=NOW - 7_100_000, type=_enum("TERMINATING"),
                       details=NS(reason=NS(code=_enum("CLOUD_PROVIDER_LAUNCH_FAILURE")), cause=_enum(""))),
                    NS(timestamp=NOW - 7_150_000, type=_enum("CREATING"), details=None)]
        return []


class FakeWorkspaceClient:
    jobs = _Jobs()
    clusters = _Clusters()
