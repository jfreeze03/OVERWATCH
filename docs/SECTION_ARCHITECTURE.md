# OVERWATCH Section Architecture

Primary sections should remain packet-first and dependency-light at import time.

Package-style sections are required when a primary section grows beyond a small
single-surface module. The convention is:

```text
.overwatch_final/sections/<section_package>/
  __init__.py
  render.py
  view_model.py
  evidence.py
  exports.py
  queries.py
  contracts.py
```

The package entry point must preserve the public import route used by
`SECTION_MODULES`, keep first paint packet-only, and load evidence/workbench
queries only after explicit actions.

Current state:

- `dba_control_room` is package-style and is the reference migration pattern.
- `cost_contract` and `alert_center` are migration candidates because they are
  large single modules with multiple workflows.
- Query Investigation root-cause helpers are owned by
  `query_investigation_root_cause.py`; the retired `query_workbench.py`
  production module must not return.

Migration candidate status is advisory during release closure. It becomes a hard
failure only when the threshold policy is explicitly enabled for that section.
