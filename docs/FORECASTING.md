# Executive Forecasting

Phase 2C adds leadership-ready forecasts for Snowflake cost, contract burn,
storage growth, warehouse pressure, and SLA risk.

## Operating Model

Forecasts follow the same enterprise operating path as the rest of OVERWATCH:

`Finding -> Owner -> Trust Level -> Business Impact -> Action -> Value Verified`

Forecasts are not verified savings. They are directional, heuristic estimates
based on the latest mart telemetry and should be reviewed with the owner before
action is taken.

## Snowflake Objects

| Object | Purpose |
| --- | --- |
| `OVERWATCH_FORECAST_CONFIG` | Forecast catalog, owner route, methodology, confidence rule, and recommended action defaults. |
| `OVERWATCH_FORECAST_HISTORY` | Forecast history and driver rows used by explicit Load panels. |
| `MART_EXECUTIVE_FORECAST_SUMMARY` | Compact first-paint summary mart for Executive Landing. |
| `SP_OVERWATCH_REFRESH_FORECASTING` | Refreshes forecast history and summary rows from existing OVERWATCH facts and marts. |

## Forecasts

| Forecast | Methodology |
| --- | --- |
| End-of-month spend | Month-to-date spend plus average observed daily spend projected through month end. |
| End-of-quarter spend | Quarter-to-date spend plus average observed daily spend projected through quarter end. |
| Contract burn | Projected quarter spend divided by `CONTRACT_TARGET_USD` or `MONTHLY_BUDGET_USD * 3` when configured. |
| Credit anomaly | Recent seven-day credit burn compared with the 30-day daily credit baseline. |
| Storage growth | Latest storage footprint plus recent daily storage growth projected 30 days forward. |
| Warehouse pressure | Recent seven-day queue pressure adjusted by movement versus the prior seven days. |
| SLA risk | Recent task and procedure incidents projected into the next seven-day operating window. |

## UI Placement

| Surface | Behavior |
| --- | --- |
| Executive Landing | First-paint compact summary from `MART_EXECUTIVE_FORECAST_SUMMARY`. |
| Cost & Contract | Explicit Load for cost, contract, and credit anomaly forecasts from `OVERWATCH_FORECAST_HISTORY`. |
| Workload Operations | Explicit Load for warehouse pressure and SLA risk forecast history. |
| DBA Control Room | Explicit Load for all forecast exceptions and driver rows. |

## Confidence Labels

Forecast confidence is one of `High`, `Medium`, or `Low`.

Confidence reflects the amount of recent mart history available and whether
required governance settings exist. It is not a guarantee that the forecast will
occur.

## Manual Snowflake Validation

After deployment:

```sql
CALL SP_OVERWATCH_REFRESH_FORECASTING();
```

Then run `snowflake/OVERWATCH_MART_VALIDATION.sql` and confirm:

- `MART_EXECUTIVE_FORECAST_SUMMARY` has at least seven forecast keys,
- `OVERWATCH_FORECAST_HISTORY` has recent rows for `ALL`, `ALFA`, and `Trexis`
  where telemetry exists,
- all confidence labels are `High`, `Medium`, or `Low`,
- methodology and main-driver text is populated,
- forecasts are not inserted into the Executive Value Ledger as verified value.

## Known Limitations

- Contract burn is `Low` confidence until `CONTRACT_TARGET_USD` or
  `MONTHLY_BUDGET_USD` is configured in `OVERWATCH_SETTINGS`.
- Forecasts use compact mart telemetry and do not run live `ACCOUNT_USAGE`
  scans on page load.
- Forecast quality depends on the mart refresh cadence and source completeness.
