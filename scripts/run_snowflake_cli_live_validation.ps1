param(
    [Parameter(Position = 0)]
    [string]$Connection = $env:OVERWATCH_SNOWFLAKE_CLI_CONNECTION,

    [string]$Profile = $(if ($env:OVERWATCH_LAUNCH_PROFILE) { $env:OVERWATCH_LAUNCH_PROFILE } else { "internal_live" }),
    [string]$Database = $env:OVERWATCH_SNOWFLAKE_VALIDATION_DATABASE,
    [string]$Schema = $env:OVERWATCH_SNOWFLAKE_VALIDATION_SCHEMA,
    [string]$Warehouse = $env:OVERWATCH_SNOWFLAKE_VALIDATION_WAREHOUSE,
    [string]$Role = $env:OVERWATCH_SNOWFLAKE_VALIDATION_ROLE,
    [string]$Company = $(if ($env:OVERWATCH_COMPANY) { $env:OVERWATCH_COMPANY } else { "ALL" }),
    [string]$Environment = $(if ($env:OVERWATCH_ENVIRONMENT) { $env:OVERWATCH_ENVIRONMENT } else { "ALL" }),
    [int]$WindowDays = $(if ($env:OVERWATCH_WINDOW_DAYS) { [int]$env:OVERWATCH_WINDOW_DAYS } else { 8 }),
    [double]$CreditPrice = $(if ($env:OVERWATCH_CREDIT_PRICE) { [double]$env:OVERWATCH_CREDIT_PRICE } else { 3.68 }),
    [switch]$RunFastRefresh,
    [switch]$RunFullRefreshDryRun,
    [switch]$SkipRefresh
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command snow -ErrorAction SilentlyContinue)) {
    $userSnow = Join-Path $env:USERPROFILE "AppData\Roaming\Python\Python312\Scripts\snow.exe"
    if (Test-Path $userSnow) {
        $env:Path = "$([System.IO.Path]::GetDirectoryName($userSnow));$env:Path"
    }
}

if (-not (Get-Command snow -ErrorAction SilentlyContinue)) {
    Write-Error "Snowflake CLI executable 'snow' is not available on PATH. Install snowflake-cli or add its Scripts directory to PATH."
}

New-Item -ItemType Directory -Force -Path "artifacts\snowflake_validation" | Out-Null
New-Item -ItemType Directory -Force -Path "artifacts\launch_readiness" | Out-Null

$argsList = @(
    "-m", "tools.contracts.snowflake_cli_live_validation",
    "--profile", $Profile,
    "--company", $Company,
    "--environment", $Environment,
    "--window-days", "$WindowDays",
    "--credit-price", "$CreditPrice"
)
if ($Connection) { $argsList += @("--connection", $Connection) }
if ($Database) { $argsList += @("--database", $Database) }
if ($Schema) { $argsList += @("--schema", $Schema) }
if ($Warehouse) { $argsList += @("--warehouse", $Warehouse) }
if ($Role) { $argsList += @("--role", $Role) }
if ($RunFastRefresh) { $argsList += "--run-fast-refresh" }
if ($RunFullRefreshDryRun) { $argsList += "--run-full-refresh-dry-run" }
if ($SkipRefresh) { $argsList += "--skip-refresh" }

python @argsList
$exitCode = $LASTEXITCODE

Write-Host "Snowflake CLI validation artifacts:"
Write-Host "  artifacts/snowflake_validation/snowflake_cli_*.json"
Write-Host "  artifacts/launch_readiness/snowflake_cli_live_gate_results.json"

exit $exitCode
