$out = "$env:USERPROFILE\Desktop\wsl2_gpu_diag.txt"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$ErrorActionPreference = "Continue"

function Log($msg) { $msg | Add-Content $out }
function Section($title) { Log "`n=== $title ===" }
function Run($title, [scriptblock]$block) {
    Section $title
    try {
        $result = & $block 2>&1
        $result | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                "SCRIPT-ERROR: $_" | Add-Content $out
            } else {
                $_ | Add-Content $out
            }
        }
    }
    catch { Log "EXCEPTION: $_`n$($_.ScriptStackTrace)" }
    Log "[section complete]"
}

"=== WSL2 GPU Diagnostics: $timestamp ===" | Out-File $out -Force

Run "SYSTEM INFO" {
    Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture | Format-List
    Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory, NumberOfProcessors | Format-List
}

Run "GPU DEVICES" {
    Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, DriverDate, Status, AdapterRAM | Format-List
}

Run "WSL VERSION" { wsl --version 2>&1 }
Run "WSL STATUS"  { wsl --status 2>&1 }
Run "WSL LIST"    { wsl --list --verbose 2>&1 }

Run "MINIDUMPS (last 10)" {
    $dumps = Get-ChildItem "$env:SystemRoot\Minidump" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 10
    if ($dumps) { $dumps | Format-Table Name, LastWriteTime, Length -AutoSize }
    else { "No minidumps found" }
}

Run "SYSTEM EVENT LOG - Critical/Error (last 48hrs)" {
    $since = (Get-Date).AddHours(-48)
    Get-WinEvent -LogName System -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $since -and $_.Level -le 2 } |
        Select-Object TimeCreated, Id, ProviderName, Message |
        Format-List
}

Run "GPU/DRIVER EVENTS (last 48hrs)" {
    $since = (Get-Date).AddHours(-48)
    Get-WinEvent -LogName System -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $since -and $_.ProviderName -match "nvlddmkm|amdkmdap|dxgkrnl|display|igfx|BasicDisplay" } |
        Select-Object TimeCreated, Id, ProviderName, Message |
        Format-List
}

Run "APPLICATION EVENT LOG - Errors (last 48hrs)" {
    $since = (Get-Date).AddHours(-48)
    Get-WinEvent -LogName Application -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $since -and $_.Level -le 2 } |
        Select-Object -First 30 TimeCreated, Id, ProviderName, Message |
        Format-List
}

Run "WHEA HARDWARE ERRORS" {
    Get-WinEvent -LogName "Microsoft-Windows-Kernel-WHEA/Errors" -ErrorAction SilentlyContinue |
        Select-Object -First 20 TimeCreated, Message | Format-List
}

Run "HYPER-V / WSL EVENTS (last 48hrs)" {
    $since = (Get-Date).AddHours(-48)
    Get-WinEvent -LogName "Microsoft-Windows-Hyper-V-Worker/Admin" -ErrorAction SilentlyContinue |
        Where-Object { $_.TimeCreated -gt $since } |
        Select-Object -First 30 TimeCreated, Message | Format-List
}

Run "MEMORY" {
    Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer, Capacity, Speed, ConfiguredClockSpeed | Format-Table -AutoSize
}

Run ".WSLCONFIG CONTENTS" {
    $wslcfg = "$env:USERPROFILE\.wslconfig"
    if (Test-Path $wslcfg) { Get-Content $wslcfg }
    else { "No .wslconfig found" }
}

Log "`n=== DONE ==="
Write-Host "Saved to: $out" -ForegroundColor Green
