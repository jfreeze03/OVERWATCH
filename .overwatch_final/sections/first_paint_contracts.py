"""Import-safe first-paint UX contracts for primary OVERWATCH sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class PrimaryFirstPaintContract:
    """Static contract for mart-summary entry and explicit detail evidence."""

    section: str
    default_view: str
    expected_lanes: tuple[str, ...]
    explicit_load_cta: str
    no_query_note: str
    allowed_cached_sources: tuple[str, ...]
    forbidden_first_paint_loaders: tuple[str, ...]


PRIMARY_FIRST_PAINT_CONTRACTS: Mapping[str, PrimaryFirstPaintContract] = {
    "Executive Landing": PrimaryFirstPaintContract(
        section="Executive Landing",
        default_view="Executive Overview",
        expected_lanes=(
            "Cost movement",
            "Cortex AI cost risk",
            "Operational risk",
            "Security risk",
            "Change summary",
            "Executive actions",
        ),
        explicit_load_cta="Load Full Executive Snapshot",
        no_query_note=(
            "Entry may read compact summary marts; full executive evidence remains behind explicit load."
        ),
        allowed_cached_sources=("section command brief mart", "local summary frame", "executive observability snapshot"),
        forbidden_first_paint_loaders=("_load_executive_snapshot", "run_query_or_raise"),
    ),
    "DBA Control Room": PrimaryFirstPaintContract(
        section="DBA Control Room",
        default_view="Morning Cockpit",
        expected_lanes=(
            "Failures",
            "Cost",
            "Queue",
            "Security",
            "Changes",
            "Action status",
        ),
        explicit_load_cta="Load Morning Cockpit",
        no_query_note=(
            "Entry may read the latest control-room summary mart; investigation detail remains explicit."
        ),
        allowed_cached_sources=("section command brief mart", "session control-room mart", "loaded control-room evidence"),
        forbidden_first_paint_loaders=("_load_control_room", "run_query_or_raise"),
    ),
    "Alert Center": PrimaryFirstPaintContract(
        section="Alert Center",
        default_view="Active Alerts",
        expected_lanes=(
            "Critical and high alerts",
            "Cortex predictive alerts",
            "Overdue alerts",
            "Action queue",
            "Delivery status",
        ),
        explicit_load_cta="Load Active Alerts",
        no_query_note="Entry may read compact alert summary marts; Load Active Alerts reads detailed alert rows.",
        allowed_cached_sources=("section command brief mart", "session alert summary", "loaded alert center data"),
        forbidden_first_paint_loaders=("_load_center_data", "run_query_or_raise"),
    ),
    "Cost & Contract": PrimaryFirstPaintContract(
        section="Cost & Contract",
        default_view="Cost Overview",
        expected_lanes=(
            "Spend movement",
            "Run rate",
            "Warehouse drivers",
            "Cortex AI cost risk",
            "Savings",
        ),
        explicit_load_cta="Open Cost Drivers",
        no_query_note="Entry may read compact cost summary marts; Open Cost Drivers loads cost facts and detail telemetry.",
        allowed_cached_sources=("section command brief mart", "session cost splash", "loaded cost cockpit data"),
        forbidden_first_paint_loaders=("_ensure_cost_splash", "_load_cost_splash_query", "run_query_or_raise"),
    ),
    "Workload Operations": PrimaryFirstPaintContract(
        section="Workload Operations",
        default_view="Workload Overview",
        expected_lanes=(
            "Slow or failed SQL",
            "Task and load failures",
            "Performance contention",
            "Recent changes",
            "Advanced DBA tools",
        ),
        explicit_load_cta="Open the right tool",
        no_query_note="Entry may read compact workload summary marts; specialist workload evidence stays workflow gated.",
        allowed_cached_sources=("section command brief mart", "session alert context", "loaded workload alert context"),
        forbidden_first_paint_loaders=(
            "_render_workload_forecast_detail",
            "_render_workload_closed_loop_detail",
            "_render_workload_command_findings",
            "run_query_or_raise",
        ),
    ),
    "Security Monitoring": PrimaryFirstPaintContract(
        section="Security Monitoring",
        default_view="Security Overview",
        expected_lanes=(
            "Logins",
            "Grants",
            "Sharing",
            "Access changes",
            "Security alerts",
        ),
        explicit_load_cta="Open Security Details",
        no_query_note=(
            "Entry may read compact security summary marts; workflow loads provide current security evidence."
        ),
        allowed_cached_sources=("section command brief mart", "session security summary", "loaded security alert context"),
        forbidden_first_paint_loaders=("_load_security_brief", "run_query_or_raise"),
    ),
}


CANONICAL_FIRST_PAINT_SECTIONS = tuple(PRIMARY_FIRST_PAINT_CONTRACTS)


def get_first_paint_contract(section: str) -> PrimaryFirstPaintContract:
    """Return the first-paint contract for a canonical section."""
    return PRIMARY_FIRST_PAINT_CONTRACTS[str(section)]


__all__ = [
    "CANONICAL_FIRST_PAINT_SECTIONS",
    "PRIMARY_FIRST_PAINT_CONTRACTS",
    "PrimaryFirstPaintContract",
    "get_first_paint_contract",
]
