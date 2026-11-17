"""Cheap pattern matching that runs before the LLM.

Gives the LLM a hint, and gives you a useful report even with --no-llm.
Extend KNOWN_PATTERNS with the failures your team keeps seeing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Hint:
    category: str
    signal: str
    typical_fix: str
    transient: bool


KNOWN_PATTERNS: list[tuple[str, Hint]] = [
    (r"java\.lang\.OutOfMemoryError|GC overhead limit exceeded|Container killed by YARN for exceeding memory|"
     r"exit code 137|DRIVER_OUT_OF_MEMORY|spark\.driver\.maxResultSize",
     Hint("memory", "Out of memory on driver/executor",
          "Use larger node type or fewer cores per executor, avoid collect()/toPandas() on large data, "
          "raise spark.driver.maxResultSize only if the result is genuinely needed on driver.", False)),
    (r"The spark driver has stopped unexpectedly|Driver is up but is not responsive|DRIVER_UNREACHABLE|"
     r"DRIVER_UNRESPONSIVE",
     Hint("driver_crash", "Driver stopped/unresponsive",
          "Usually driver memory pressure or a long GC pause; check driver logs and Ganglia/metrics, "
          "size the driver up, move heavy work off the driver.", False)),
    (r"CLOUD_PROVIDER_LAUNCH_FAILURE|AZURE_QUOTA_EXCEEDED_EXCEPTION|QuotaExceeded|"
     r"SKU.*not available|AllocationFailed|ZonalAllocationFailed|INSTANCE_POOL_CLUSTER_FAILURE",
     Hint("cluster_launch_capacity", "Cluster could not get VMs (quota/capacity)",
          "Check Azure vCPU quota for the VM family in the region, try another SKU/zone, use an instance "
          "pool with idle instances, add retries on the task.", True)),
    (r"SUBNET_EXHAUSTED|Subnet.*does not have enough|IP address.*exhausted|NETWORK_CONFIGURATION_FAILURE|"
     r"NSG|AZURE_VNET_CONFIGURATION_FAILURE",
     Hint("cluster_launch_network", "VNet/subnet problem during cluster launch",
          "Check free IPs in the workspace host/container subnets, NSG and UDR rules, and firewall egress "
          "to the Databricks control plane.", False)),
    (r"BOOTSTRAP_TIMEOUT|INIT_SCRIPT_FAILURE|init script.*(failed|exit)",
     Hint("init_script", "Init script or bootstrap failed",
          "Open the init script logs on the cluster log destination; check package mirrors and egress, "
          "pin versions, make the script idempotent.", False)),
    (r"ModuleNotFoundError|No module named|ImportError|ClassNotFoundException|NoClassDefFoundError|"
     r"Library installation failed|LIBRARY_INSTALLATION",
     Hint("dependency", "Missing or failed library",
          "Attach the library to the job cluster/task, pin a compatible version for the DBR version, "
          "check the private PyPI/Maven mirror is reachable.", False)),
    (r"PERMISSION_DENIED|does not have (USE|SELECT|MODIFY|READ)|AuthorizationPermissionMismatch|"
     r"This request is not authorized|403 Forbidden|Insufficient privileges|User does not have permission",
     Hint("permissions", "Permission denied (UC / storage / workspace)",
          "Grant the job's run-as identity the missing privilege (UC grant, storage RBAC, secret scope ACL). "
          "Check if run-as owner changed recently.", False)),
    (r"ConcurrentAppendException|ConcurrentDeleteReadException|ConcurrentModificationException|"
     r"MetadataChangedException|ProtocolChangedException",
     Hint("delta_concurrency", "Delta concurrent write conflict",
          "Partition writes so jobs don't overlap, use explicit partition predicates in MERGE, schedule "
          "conflicting jobs apart, add retry on the task.", True)),
    (r"AnalysisException|TABLE_OR_VIEW_NOT_FOUND|UNRESOLVED_COLUMN|cannot resolve|Path does not exist|"
     r"FileNotFoundException",
     Hint("data_or_schema", "Missing table/column/path or schema drift",
          "Check upstream job produced the data, look for schema change, enable schema evolution only if "
          "intended.", False)),
    (r"Run timed out|TIMEDOUT|timeout_seconds",
     Hint("timeout", "Run exceeded timeout",
          "Compare duration with past runs; look for data volume growth or skew; raise timeout only after "
          "fixing the slowdown.", False)),
    (r"Connection reset|Connection refused|SocketTimeoutException|Temporary failure in name resolution|"
     r"503 Service Unavailable|429 Too Many Requests|RESOURCE_EXHAUSTED",
     Hint("transient_network", "Network / throttling error",
          "Likely transient; add task retries with backoff and check the downstream service health.", True)),
    (r"SPOT_INSTANCE_TERMINATION|lost executor|ExecutorLostFailure|Decommission",
     Hint("spot_eviction", "Spot VM eviction / executor lost",
          "Use on-demand driver (first_on_demand >= 1), spot with fallback to on-demand, add retries.", True)),
]

_COMPILED = [(re.compile(p, re.I), h) for p, h in KNOWN_PATTERNS]


def evidence_lines(text: str, category: str, limit: int = 3) -> list[str]:
    rx = next(r for r, h in _COMPILED if h.category == category)
    return [ln.strip()[:300] for ln in (text or "").splitlines() if rx.search(ln)][:limit]


def classify(text: str) -> list[Hint]:
    seen, hints = set(), []
    for rx, hint in _COMPILED:
        if hint.category not in seen and rx.search(text or ""):
            seen.add(hint.category)
            hints.append(hint)
    return hints
