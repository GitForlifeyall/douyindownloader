param(
    [string]$ProfileName = "account_1"
)

$pyExe = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $pyExe = ".venv\Scripts\python.exe"
} elseif (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe") {
    $pyExe = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
}

& $pyExe "tools\flow_profile_manager.py" launch "$ProfileName"
