# sections/warehouse_health_helpers.py - Pure Warehouse Health decision helpers.
from __future__ import annotations

from utils.primitives import safe_float


def _warehouse_capacity_score(
    queued_queries: int,
    spill_queries: int,
    high_latency_queries: int,
    total_queries: int,
    credit_spike_pct: float,
) -> int:
    total = max(int(total_queries or 0), 1)
    queue_pct = safe_float(queued_queries) / total * 100
    spill_pct = safe_float(spill_queries) / total * 100
    latency_pct = safe_float(high_latency_queries) / total * 100
    spike_pct = max(safe_float(credit_spike_pct), 0)
    penalty = (
        min(queue_pct * 2.0, 28)
        + min(spill_pct * 1.8, 24)
        + min(latency_pct * 1.1, 18)
        + min(spike_pct / 4, 20)
    )
    return max(0, min(100, int(round(100 - penalty))))


def _warehouse_capacity_action_for(signal: str) -> tuple[str, str]:
    signal = str(signal or "").upper()
    if "QUEUE" in signal:
        return (
            "Review multi-cluster policy, warehouse size, auto-resume latency, and workload routing.",
            "-- Queue pressure: inspect WAREHOUSE_LOAD_HISTORY and top queued QUERY_HISTORY rows.",
        )
    if "SPILL" in signal:
        return (
            "Inspect top spilling queries and consider query rewrites, clustering, or a larger warehouse for this workload.",
            "-- Spill pressure: use GET_QUERY_OPERATOR_STATS for top remote-spill query IDs.",
        )
    if "CREDIT" in signal:
        return (
            "Compare current burn to prior period and confirm whether the spike is business demand, idle time, or runaway workload.",
            "-- Credit spike: reconcile WAREHOUSE_METERING_HISTORY with query-attributed drivers.",
        )
    return (
        "Review p95 latency, query volume, and top query patterns before changing warehouse configuration.",
        "-- Latency pressure: inspect high elapsed query signatures and warehouse load.",
    )


def _warehouse_capacity_workflow_for(signal: str) -> str:
    signal = str(signal or "").upper()
    if "SPILL" in signal:
        return "Spill & Memory"
    if "CREDIT" in signal:
        return "Efficiency"
    if "QUEUE" in signal:
        return "Workload Heatmap"
    return "Overview & Scaling"
