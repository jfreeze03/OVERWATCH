# Snowflake CLI Live Validation

This lane lets an operator prove OVERWATCH against a real Snowflake account from a local machine or self-hosted runner. It records sanitized execution metadata, packet values, formula comparisons, and query-budget proof. It must not record passwords, tokens, private keys, connection strings, raw SQL, procedure bodies, stack traces, or raw Snowflake errors.

## Create And Test A Connection

Install and configure Snowflake CLI outside this repo:

```powershell
snow connection add
snow connection test -c <connection>
```

If PowerShell cannot find `snow`, add your Python Scripts folder to `PATH`, for example:

```powershell
$snowScripts = "$env:APPDATA\Python\Python312\Scripts"
$env:Path = "$snowScripts;$env:Path"
snow --version
```

## Run OVERWATCH Validation

Windows PowerShell:

```powershell
.\scripts\run_snowflake_cli_live_validation.ps1 <connection>
```

Shell:

```bash
scripts/run_snowflake_cli_live_validation.sh <connection>
```

The wrappers set safe defaults, create artifact folders, avoid echoing secrets, and run:

```powershell
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live
```

Programmatic access token (PAT) runs are supported without recording the token file path in artifacts:

```powershell
$env:OVERWATCH_SNOWFLAKE_CLI_AUTHENTICATOR = "PROGRAMMATIC_ACCESS_TOKEN"
$env:OVERWATCH_SNOWFLAKE_CLI_TOKEN_FILE_PATH = "C:\secure\overwatch_pat.txt"
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live --authenticator PROGRAMMATIC_ACCESS_TOKEN --token-file-path "C:\secure\overwatch_pat.txt" --database DBA_MAINT_DB --schema OVERWATCH --warehouse WH_ALFA_OVERWATCH --company ALFA --environment ALL --window-days 7 --skip-refresh
```

Artifacts only record `token_file_supplied=true`; they must never record the PAT, token file path, temp SQL file path, raw SQL body, account URL, stack trace, or raw Snowflake error text.

Common options:

```powershell
.\scripts\run_snowflake_cli_live_validation.ps1 <connection> -Database DBA_MAINT_DB -Schema OVERWATCH -Warehouse WH_ALFA_OVERWATCH
.\scripts\run_snowflake_cli_live_validation.ps1 <connection> -RunFastRefresh
.\scripts\run_snowflake_cli_live_validation.ps1 <connection> -SkipRefresh
```

FULL refresh validation is dry-run only unless the app procedure honors dry-run mode. Destructive validation requires `OVERWATCH_ALLOW_DESTRUCTIVE_SNOWFLAKE_VALIDATION=1`.

## Formula-Only And Query-Budget Proof

The default run validates setup SQL, packet/flat values, COST_DB-authority formulas, and summary-card values. To include query-history budget proof, set a query tag prefix and enable plan proof:

```powershell
$env:OVERWATCH_QUERY_PLAN_PROOF = "1"
$env:OVERWATCH_QUERY_TAG_PREFIX = "OVERWATCH_VALIDATION"
.\scripts\run_snowflake_cli_live_validation.ps1 <connection> -SkipRefresh
```

Query-budget proof combines Snowflake query-history rows for executed tagged queries with producer-backed runtime artifacts for expected-zero boundaries such as warm first paint, route actions, and Query Search no-click. If query-history permission is missing, the tool writes an explicit skipped artifact with a sanitized reason. `internal_live` and `prod_candidate` require query-history/runtime proof or an owner-approved waiver.

## Generated Artifacts

The validator writes:

- `artifacts/snowflake_validation/snowflake_cli_capability_results.json`
- `artifacts/snowflake_validation/snowflake_cli_connection_results.json`
- `artifacts/snowflake_validation/snowflake_cli_execution_manifest.json`
- `artifacts/snowflake_validation/snowflake_cli_manifest_reconciliation_results.json`
- `artifacts/snowflake_validation/snowflake_cli_setup_validation_results.json`
- `artifacts/snowflake_validation/setup_migration_live_results.json`
- `artifacts/snowflake_validation/packet_availability_matrix_results.json`
- `artifacts/snowflake_validation/snowflake_cli_packet_availability_results.json`
- `artifacts/snowflake_validation/snowflake_cli_formula_value_results.json`
- `artifacts/snowflake_validation/snowflake_cli_packet_value_results.json`
- `artifacts/snowflake_validation/snowflake_cli_summary_card_value_results.json`
- `artifacts/snowflake_validation/snowflake_cli_cost_reconciliation_results.json`
- `artifacts/snowflake_validation/snowflake_cli_query_budget_results.json`
- `artifacts/snowflake_validation/snowflake_cli_temp_file_hygiene_results.json`
- `artifacts/launch_readiness/packet_availability_gate_results.json`
- `artifacts/launch_readiness/live_cost_reconciliation_gate_results.json`
- `artifacts/launch_readiness/snowflake_cli_formula_value_gate_results.json`
- `artifacts/launch_readiness/snowflake_cli_temp_file_hygiene_gate_results.json`
- `artifacts/launch_readiness/setup_migration_live_gate_results.json`
- `artifacts/launch_readiness/snowflake_cli_live_gate_results.json`
- `artifacts/release_candidate/snowflake_cli_release_results.json`

Pass/fail is summarized in `artifacts/launch_readiness/snowflake_cli_live_gate_results.json`. Launch readiness consumes that artifact and blocks `internal_live` and `prod_candidate` unless live CLI proof passes or a signed waiver exists.

## Recommended Local Sequence

1. Test the configured connection:

```powershell
snow connection test -c <connection>
```

2. Run formula-only validation without refresh:

```powershell
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live --company ALFA --environment ALL --window-days 7 --skip-refresh
```

Token-backed equivalent:

```powershell
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live --authenticator PROGRAMMATIC_ACCESS_TOKEN --token-file-path "C:\secure\overwatch_pat.txt" --database DBA_MAINT_DB --schema OVERWATCH --warehouse WH_ALFA_OVERWATCH --company ALFA --environment ALL --window-days 7 --skip-refresh
```

3. Run FAST refresh validation only when you want that procedure exercised:

```powershell
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live --company ALFA --environment ALL --window-days 7 --run-fast-refresh
```

4. Run query-budget validation with query-history proof:

```powershell
$env:OVERWATCH_QUERY_PLAN_PROOF = "1"
$env:OVERWATCH_QUERY_TAG_PREFIX = "OVERWATCH_VALIDATION"
python -m tools.contracts.snowflake_cli_live_validation --connection <connection> --profile internal_live --company ALFA --environment ALL --window-days 7 --skip-refresh
```

5. Run with the PowerShell wrapper:

```powershell
.\scripts\run_snowflake_cli_live_validation.ps1 <connection> -SkipRefresh
```

6. Run with the bash wrapper:

```bash
scripts/run_snowflake_cli_live_validation.sh <connection>
```

## Interpreting Pass And Live Proof

`snowflake_cli_gate_passed=true` means the profile-specific gate passed. In `internal_fixture`, a skipped CLI run may pass the gate so CI can run without credentials. That is not live proof. Real live proof requires `snowflake_cli_live_executed=true` and `snowflake_cli_live_passed=true`.

The capability artifact must show JSON output support. The validator uses machine-readable Snowflake CLI output and fails rather than scraping table text. Formula rows compare live expected values, packet values, flat values, and rendered values when rendered summary artifacts are available.

Generated validation SQL is executed through short-lived temporary `snow sql -f` files so command lines do not expose SQL bodies. `snowflake_cli_temp_file_hygiene_results.json` proves those files were deleted and that no temp file path was stored.

## Waiver Policy

`internal_fixture` may skip local CLI proof with an explicit reason. `internal_live` expects local or runner-backed Snowflake CLI proof; skips require owner, reason, review note, expiration, and approving surface. `prod_candidate` requires live CLI/Snowflake proof unless a signed waiver is present. Waivers should use one of these gates:

- `snowflake_cli_live_validation`
- `live_snowflake_validation`
- `snowflake_execution_validation`

Do not place secrets in waivers, command-line arguments, issue comments, release notes, or artifact files.

## Troubleshooting Live Findings

- Refresh required / no packet: inspect `packet_availability_matrix_results.json` for exact-scope, relaxed-scope, alternate-window, flat-current, and last-known-good counts.
- Window mismatch: the Streamlit date range `2026/06/21-2026/06/28` is treated as seven completed packet days. If a user selects an inclusive eight-date range, validation maps it to the seven-day packet convention and reports the closest available packet.
- Account billing undercount: inspect `snowflake_cli_cost_reconciliation_results.json`; cloud-services adjustment must be present or explicitly unavailable, never silently zeroed.
- Cortex service type unknown: inspect `cortex_service_type_live_results.json` and the formula rows for unknown-review status. Unknown services do not enter daily Cortex spend until approved.
- Query history permission missing: `snowflake_cli_query_budget_results.json` records a skipped row with a sanitized reason. `internal_live` and `prod_candidate` need proof or a waiver.
- Setup validation failed: inspect `snowflake_cli_setup_validation_results.json`; errors are sanitized and SQL bodies are omitted.
- Packet exists but flat is missing: the packet availability gate fails and points to the affected section/scope.
- Rendered card mismatch: inspect `snowflake_cli_summary_card_value_results.json` and `rendered_formula_results.json`; summary cards must render packet/flat formula values, not optional detail dataframes.
