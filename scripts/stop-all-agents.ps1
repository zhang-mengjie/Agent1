# 停止 rag / cs / finance / spine（8001/8002/8003/8004）及相关 MCP / exe
# 【易错点】
# 1. 不要用 Get-Process 判断端口是否空闲：有的 PID netstat 能看到，Get-Process 却失败，
#    但服务其实还在（HTTP 仍 200）。必须以 Listen 为准。
# 2. 若返回 Access Denied：请到「启动 xxx-agent」那个终端按 Ctrl+C，
#    或在任务管理器结束对应 python/uvicorn。
$ErrorActionPreference = "Continue"
$ports = @(8001, 8002, 8003, 8004)

function Stop-Tree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Tree -ProcessId ([int]$_.ProcessId) }
    & taskkill.exe /F /T /PID $ProcessId 2>$null | Out-Null
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-ListenPids([int]$Port) {
    $ids = New-Object System.Collections.Generic.List[int]
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
            $procId = [int]$_.OwningProcess
            if ($procId -gt 0 -and -not $ids.Contains($procId)) { $ids.Add($procId) }
        }
    return ,$ids.ToArray()
}

foreach ($p in $ports) {
    foreach ($procId in (Get-ListenPids -Port $p)) {
        Write-Output "Stopping PID $procId on port $p ..."
        Stop-Tree -ProcessId $procId
    }
}

$pattern = 'rag_agent\.main:app|cs_agent\.main:app|finance_agent\.main:app|spine_agent\.main:app|rag_agent\.mcp_server|cs_agent\.mcp_server|finance_agent\.mcp_server|spine_agent\.mcp_server|rag-agent\.exe|cs-agent\.exe|finance-agent\.exe|spine-agent\.exe'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match $pattern) } |
    ForEach-Object {
        Write-Output "Stopping matched process $($_.ProcessId)"
        Stop-Tree -ProcessId ([int]$_.ProcessId)
    }

Start-Sleep -Milliseconds 800

$left = @()
foreach ($p in $ports) {
    $live = @(Get-ListenPids -Port $p)
    if ($live.Count -gt 0) {
        $left += ("${p}(PID " + ($live -join ",") + ")")
    }
}

if ($left.Count) {
    Write-Output ""
    Write-Output ("FAILED: still LISTEN on " + ($left -join "; "))
    Write-Output "Access may be denied for these PIDs."
    Write-Output "Fix: open the terminal panel that started the agent and press Ctrl+C,"
    Write-Output "or end the python/uvicorn process in Task Manager."
    exit 1
}

Write-Output "Stopped all agents (8001/8002/8003/8004)."
