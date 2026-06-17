# OVERWATCH Implementation Notes

This file records user-facing implementation changes that should be documented
outside the Streamlit app UI.

## 2026-06-17 - Warehouse Advisor Boundary

- `Cost & Contract > Recommendations and action queue > Warehouse Advisor` is
  the recommendation surface for warehouse tuning. It ranks auto-suspend,
  downsize, pressure, timeout, and guardrail findings with estimated monthly and
  annual savings where the savings can be quantified.
- The Warehouse Advisor must not present generated `ALTER WAREHOUSE` scripts,
  setup DDL, or execution-ready SQL. It should show the recommendation, current
  signal, estimated savings, safe next step, validation telemetry, and the Admin
  workflow route.
- State-changing warehouse changes belong in `DBA Control Room > Admin >
  Warehouse Settings`, where preview, typed confirmation, rollback context, and
  audit logging remain guarded.
- Savings shown by the advisor are estimates until a post-change complete
  telemetry window confirms lower credits without worse queue, spill, p95, or
  failure behavior.
