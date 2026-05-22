$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = "C:\Users\jfree\AppData\Local\Programs\Python\Python312\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        $python = "python"
    }
    & $python -m venv (Join-Path $repoRoot ".venv")
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $repoRoot "requirements.txt")
}

& $venvPython -m streamlit run (Join-Path $repoRoot ".overwatch_final\app.py")
