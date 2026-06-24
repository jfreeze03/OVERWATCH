# OVERWATCH Query Tuning Validation - 33ea8b6

## Scope
- Commit under validation: `33ea8b691414855e81a5abd3dc3638d56c2cfae5`
- Validation query tag: `OVERWATCH|QUERY_TUNING_33EA8B6`
- Date: `2026-06-24`
- Purpose: validate the repeated Snowflake query tuning for cost reconciliation and shared security summaries.
- Release policy note: browser release posture is unchanged. The authoritative browser release gate remains ramp-24 RERUN9, and strict ramp-12 remains diagnostic-only local-client capacity evidence.

## Prior Tuning Candidates
The pre-change read-only `ACCOUNT_USAGE.QUERY_HISTORY` scan identified two repeated SELECT fingerprints as tuning candidates:

| Query Hash | Surface | 7-Day Count | 7-Day TB Scanned | Avg Elapsed | P95 Elapsed | Main Finding |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `0d8c864de8197141b258ff2f05a29839` | Cost reconciliation | 210 | 0.114 | 8.95s | 12.44s | Compilation dominated; reconciliation SQL scanned `QUERY_HISTORY` twice. |
| `31a96e9323e2246f3adbe12e5ec851ca` | Shared security mart brief | 330 | 0.143 | 5.00s | 7.19s | Compilation dominated; role-scope predicates repeated `GRANTS_TO_USERS` subqueries. |

## SQL Shape Validation
- Cost reconciliation now defines `scoped_query_history` once and reuses it from `query_exec_share` and `allocated_daily`.
- Cost reconciliation SQL contains exactly one direct `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` reference.
- Shared security live and mart builders define a single `role_scope` CTE when ALFA/Trexis role-scope rules require it.
- `ALL` company scope does not inject `role_scope`, ALFA/Trexis database filters, or company fact filters.
- ALFA semantics still exclude TRXS-only users without excluding mixed-role admin users.
- Trexis semantics still require TRXS-only role scope where role patterns apply.

## Live Snowflake Validation
All validation queries completed successfully with zero query errors. Immediate query-history details came from `INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER`; partition count and remote spill were not exposed by that source for these rows.

| Query | Query ID | Rows | Snowflake Elapsed | Compile | Execute | Bytes Scanned | Queue |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cost reconciliation, 30d, query attribution | `01c54551-0206-1927-000e-d64a00054306` | 7 | 9.837s | 4.739s | 4.899s | 0 | 0 |
| cost reconciliation, 30d, allocated fallback | `01c54552-0206-1760-000e-d64a000531f2` | 7 | 6.625s | 3.955s | 2.670s | 0 | 0 |
| shared security live summary, ALFA | `01c54552-0206-175c-000e-d64a0004940e` | 1 | 7.556s | 4.864s | 2.692s | 0 | 0 |
| shared security live summary, Trexis | `01c54552-0206-1760-000e-d64a000531f6` | 1 | 4.095s | 3.446s | 0.649s | 0 | 0 |
| shared security mart brief, ALFA | `01c54552-0206-1927-000e-d64a0005430a` | 1 | 3.770s | 3.107s | 0.663s | 0 | 0 |
| shared security mart brief, Trexis | `01c54552-0206-184d-000e-d64a00047986` | 1 | 3.202s | 2.755s | 0.447s | 0 | 0 |

## Comparison Note
The duplicate metadata source references were reduced in generated SQL and are covered by unit contracts. A follow-up `ACCOUNT_USAGE` comparison query was attempted after the live validation, but OAuth callback authentication timed out before the comparison query could run. Because of that, this note records successful live execution and SQL-shape reduction, not a claimed measured before/after performance win.

## Validation Commands
- `python -m unittest tests.test_formula_regressions tests.test_shared_metrics`: PASS, 355 tests.
- `python -m unittest discover tests`: PASS.
- `python -m ruff check .overwatch_final\utils\shared_metrics_security.py tests\test_shared_metrics.py`: PASS.
- `python -m compileall .overwatch_final\utils\shared_metrics_security.py tests\test_shared_metrics.py`: PASS.

