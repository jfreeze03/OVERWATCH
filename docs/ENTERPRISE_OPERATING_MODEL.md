# Enterprise Operating Model

Phase 1 enterprise capability delivery connects the app around one operating
path:

Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified

The implementation is mart-first. First paint reads compact OVERWATCH summary
tables only. Evidence, source diagnostics, and ledger detail stay behind
explicit Load buttons.

## Capabilities

| Capability | Primary section | Detail section | First-paint source | Detail load |
|---|---|---|---|---|
| Data Trust Layer | Executive Landing | DBA Control Room | `MART_DATA_TRUST_SUMMARY` | `OVERWATCH_DATA_TRUST_STATUS` |
| Ownership Map | Alert Center, Security Monitoring | Alert Center, Security Monitoring | `MART_OPERATIONAL_OWNER_COVERAGE` | Existing alert/security detail lanes |
| Executive Value Ledger | Executive Landing | Cost & Contract | `MART_EXECUTIVE_VALUE_LEDGER` | `OVERWATCH_VALUE_LEDGER` plus cost action queue rows |
| App Self-Observability | Executive Landing | DBA Control Room | `MART_APP_OBSERVABILITY_SUMMARY` | `OVERWATCH_APP_OBSERVABILITY` |
| Production Readiness | Executive Landing | DBA Control Room | `MART_PRODUCTION_READINESS_SUMMARY` | `OVERWATCH_PRODUCTION_VALIDATION_STATUS` |
| Executive Scorecard | Executive Landing | DBA Control Room, Cost & Contract, Security Monitoring, Alert Center | `MART_EXECUTIVE_SCORECARD_SUMMARY` | `OVERWATCH_EXECUTIVE_SCORECARD_HISTORY` |
| Executive Forecasting | Executive Landing | DBA Control Room, Cost & Contract, Workload Operations | `MART_EXECUTIVE_FORECAST_SUMMARY` | `OVERWATCH_FORECAST_HISTORY` |
| Change Intelligence | Executive Landing | DBA Control Room, Cost & Contract, Workload Operations, Security Monitoring, Alert Center | `MART_CHANGE_INTELLIGENCE_SUMMARY` | `OVERWATCH_CHANGE_EVENT`, `OVERWATCH_CHANGE_CORRELATION` |

## Snowflake Objects

| Object | Purpose |
|---|---|
| `OVERWATCH_DATA_TRUST_SOURCE` | Source freshness policy and confidence catalog. |
| `OVERWATCH_DATA_TRUST_STATUS` | Latest source-level trust diagnostics. |
| `MART_DATA_TRUST_SUMMARY` | Compact trust rollup for first paint. |
| `OVERWATCH_OPERATIONAL_OWNER_MAP` | Operational route fallback by entity type; not a generic directory. |
| `MART_OPERATIONAL_OWNER_COVERAGE` | Alert/security/action ownership coverage and route gaps. |
| `OVERWATCH_VALUE_LEDGER` | Durable value proof rows with expected and actual verified savings. |
| `MART_EXECUTIVE_VALUE_LEDGER` | Compact value rollup that separates verified savings from unverified estimates. |
| `OVERWATCH_APP_OBSERVABILITY` | Recent app runtime/query-tag health detail from app logs. |
| `MART_APP_OBSERVABILITY_SUMMARY` | Compact app health rollup for first paint. |
| `SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL` | Refreshes all enterprise operating-model summaries from existing OVERWATCH data. |
| `MART_PRODUCTION_READINESS_SUMMARY` | Compact Phase 2A deployment, validation, privilege, refresh, config, freshness, and environment readiness rollup. |
| `OVERWATCH_PRODUCTION_VALIDATION_STATUS` | Explicit-load Phase 2A validation proof rows. |
| `OVERWATCH_EXECUTIVE_SCORECARD_CONFIG` | Phase 2B leadership score thresholds, owner routes, and action defaults. |
| `OVERWATCH_EXECUTIVE_SCORECARD_HISTORY` | Explicit-load Phase 2B score driver history. |
| `MART_EXECUTIVE_SCORECARD_SUMMARY` | Compact Phase 2B leadership health score summary. |
| `SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD` | Refreshes leadership scores from existing OVERWATCH marts and app tables. |
| `OVERWATCH_FORECAST_CONFIG` | Phase 2C forecast catalog, owner routes, methodology, and confidence rules. |
| `OVERWATCH_FORECAST_HISTORY` | Explicit-load Phase 2C forecast driver history. |
| `MART_EXECUTIVE_FORECAST_SUMMARY` | Compact Phase 2C leadership forecasting summary. |
| `SP_OVERWATCH_REFRESH_FORECASTING` | Refreshes cost, contract, storage, pressure, and SLA forecasts from OVERWATCH facts. |
| `OVERWATCH_CHANGE_RULE` | Phase 2D change category, owner route, risk, confidence, source, and business-impact catalog. |
| `OVERWATCH_CHANGE_EVENT` | Explicit-load Phase 2D normalized change event history. |
| `OVERWATCH_CHANGE_CORRELATION` | Explicit-load Phase 2D possible correlation history. |
| `MART_CHANGE_INTELLIGENCE_SUMMARY` | Compact Phase 2D recent-change and risk summary. |
| `SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE` | Refreshes change events, possible correlations, and compact summary rows. |

## Confidence Labels

All enterprise trust/value/app metrics must use one of:

- `exact`
- `allocated`
- `estimated`
- `fallback`

Validation SQL checks these labels across the new objects.

## Safety Boundaries

- No broad live `ACCOUNT_USAGE` scans are introduced for first paint.
- No detail evidence loads run unless the operator clicks a Load button.
- No remediation is silently executed.
- Value estimates are not counted as realized savings unless verified telemetry exists.
- Ownership coverage is operational routing only; it is not an owner directory or governance approval system.
- Production readiness role and privilege proof stays explicit; see `docs/PRODUCTION_READINESS.md`.
- Change Intelligence uses `possible correlation` until separate evidence proves
  causality; it does not execute remediation.

## Manual Snowflake Validation

After deploying DDL, run:

```sql
CALL SP_OVERWATCH_REFRESH_ENTERPRISE_OPERATING_MODEL();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- new objects are present,
- object count contract passes,
- confidence label check passes,
- unverified value is not counted as realized savings,
- enterprise summary marts have recent rows,
- caller role/warehouse context is expected.

For Phase 2A production validation, also run:

```sql
CALL SP_OVERWATCH_REFRESH_PRODUCTION_READINESS();
```

Then review `MART_PRODUCTION_READINESS_SUMMARY`,
`OVERWATCH_PRODUCTION_VALIDATION_STATUS`, and the production readiness checks in
`snowflake/OVERWATCH_MART_VALIDATION.sql`.

For Phase 2B Executive Scorecard validation, also run:

```sql
CALL SP_OVERWATCH_REFRESH_EXECUTIVE_SCORECARD();
```

Then review `MART_EXECUTIVE_SCORECARD_SUMMARY`,
`OVERWATCH_EXECUTIVE_SCORECARD_HISTORY`, `docs/EXECUTIVE_SCORECARD.md`, and the
scorecard checks in `snowflake/OVERWATCH_MART_VALIDATION.sql`.

Forecasting:

```sql
CALL SP_OVERWATCH_REFRESH_FORECASTING();
```

Then review `MART_EXECUTIVE_FORECAST_SUMMARY`, `OVERWATCH_FORECAST_HISTORY`,
`docs/FORECASTING.md`, and the forecasting checks in
`snowflake/OVERWATCH_MART_VALIDATION.sql`. Forecasted savings are not verified
value and must stay separate from `MART_EXECUTIVE_VALUE_LEDGER`.

Change Intelligence:

```sql
CALL SP_OVERWATCH_REFRESH_CHANGE_INTELLIGENCE();
```

Then review `MART_CHANGE_INTELLIGENCE_SUMMARY`, `OVERWATCH_CHANGE_EVENT`,
`OVERWATCH_CHANGE_CORRELATION`, `docs/CHANGE_INTELLIGENCE.md`, and the Change
Intelligence checks in `snowflake/OVERWATCH_MART_VALIDATION.sql`. Correlation
rows are timing/entity candidates only and should remain labeled
`possible correlation`.
