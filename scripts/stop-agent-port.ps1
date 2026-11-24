param(
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$Pattern = "",
    [string]$Name = "agent"
)

# Pattern contains '|'. VS Code runs tasks via powershell -Command, which strips
# double quotes, so '|' becomes a pipeline and spine_agent\.mcp_server is
# treated as a module. Tasks pass -Name only; the regex lives here.
if (-not $Pattern) {
    $builtins = @{
        "rag-agent"     = 'rag_agent\.main:app|rag_agent\.mcp_server|rag-agent\.exe'
        "cs-agent"      = 'cs_agent\.main:app|cs_agent\.mcp_server|cs-agent\.exe'
        "finance-agent" = 'finance_agent\.main:app|finance_agent\.mcp_server|finance-agent\.exe'
        "spine-agent"   = 'spine_agent\.main:app|spine_agent\.mcp_server|spine-agent\.exe'
    }
    if (-not $builtins.ContainsKey($Name)) {
        Write-Output "FAILED: no pattern for $Name"
        exit 1
    }
    $Pattern = $builtins[$Name]
}

$ErrorActionPreference = "Continue"

function Stop-Tree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Tree -ProcessId ([int]$_.ProcessId) }
    & taskkill.exe /F /T /PID $ProcessId 2>$null | Out-Null
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        $procId = [int]$_.OwningProcess
        if ($procId -gt 0) {
            Write-Output "Stopping PID $procId on port $Port ..."
            Stop-Tree -ProcessId $procId
        }
    }

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match $Pattern) } |
    ForEach-Object { Stop-Tree -ProcessId ([int]$_.ProcessId) }

Start-Sleep -Milliseconds 500

$still = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 })
if ($still.Count) {
    $pids = ($still | ForEach-Object { $_.OwningProcess }) -join ","
    Write-Output ("FAILED: port $Port still LISTEN (PID $pids). Press Ctrl+C in the start-agent terminal, or kill it in Task Manager.")
    exit 1
}
Write-Output ("Stopped " + $Name)
