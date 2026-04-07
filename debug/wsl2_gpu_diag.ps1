$out = "$env:USERPROFILE\Desktop\wsl2_gpu_diag.txt"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"=== WSL2 GPU Diagnostics: $timestamp ===" | Out-File $out

# System info
"`n=== SYSTEM INFO ===" | Add-Content $out
Get-ComputerInfo | Select-Object WindowsVersion, OsArchitecture, CsProcessors, CsTotalPhysicalMemory | Format-List | Add-Content $out

# GPU info
"`n=== GPU DEVICES ===" | Add-Content $out
Get-WmiObject Win32_VideoController | Select-Object Name, DriverVersion, DriverDate, Status, AdapterRAM | Format-List | Add-Content $out

# WSL version and config
"`n=== WSL VERSION ===" | Add-Content $out
wsl --version 2>&1 | Add-Content $out
"`n=== WSL STATUS ===" | Add-Content $out
wsl --status 2>&1 | Add-Content $out
"`n=== WSL LIST ===" | Add-Content $out
wsl --list --verbose 2>&1 | Add-Content $out

# Check for crash dumps
"`n=== MINIDUMPS (last 10) ===" | Add-Content $out
Get-ChildItem "$env:SystemRoot\Minidump" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | Format-Table Name, LastWriteTime, Length | Add-Content $out

# Recent critical/error events - System log
"`n=== SYSTEM EVENT LOG (Critical/Error, last 48hrs) ===" | Add-Content $out
$since = (Get-Date).AddHours(-48)
Get-WinEvent -LogName System -ErrorAction SilentlyContinue |
    Where-Object { $_.TimeCreated -gt $since -and $_.Level -le 2 } |
    Select-Object TimeCreated, Id, ProviderName, Message |
    Format-List | Add-Content $out

# GPU/display driver specific events
"`n=== GPU/DRIVER EVENTS (last 48hrs) ===" | Add-Content $out
Get-WinEvent -LogName System -ErrorAction SilentlyContinue |
    Where-Object { $_.TimeCreated -gt $since -and ($_.ProviderName -match "nvlddmkm|amdkmdap|dxgkrnl|display|igfx|BasicDisplay") } |
    Select-Object TimeCreated, Id, ProviderName, Message |
    Format-List | Add-Content $out

# Application log errors
"`n=== APPLICATION EVENT LOG (Errors, last 48hrs) ===" | Add-Content $out
Get-WinEvent -LogName Application -ErrorAction SilentlyContinue |
    Where-Object { $_.TimeCreated -gt $since -and $_.Level -le 2 } |
    Select-Object -First 30 TimeCreated, Id, ProviderName, Message |
    Format-List | Add-Content $out

# WHEA hardware errors (hardware-level crash info)
"`n=== WHEA HARDWARE ERRORS ===" | Add-Content $out
Get-WinEvent -LogName "Microsoft-Windows-Kernel-WHEA/Errors" -ErrorAction SilentlyContinue |
    Select-Object -First 20 TimeCreated, Message | Format-List | Add-Content $out

# Hyper-V / WSL events
"`n=== HYPER-V / WSL EVENTS (last 48hrs) ===" | Add-Content $out
Get-WinEvent -LogName "Microsoft-Windows-Hyper-V-Worker/Admin" -ErrorAction SilentlyContinue |
    Where-Object { $_.TimeCreated -gt $since } |
    Select-Object -First 30 TimeCreated, Message | Format-List | Add-Content $out

# Memory info
"`n=== MEMORY ===" | Add-Content $out
Get-WmiObject Win32_PhysicalMemory | Select-Object Manufacturer, Capacity, Speed, ConfiguredClockSpeed | Format-Table | Add-Content $out

# .wslconfig if present
"`n=== .WSLCONFIG CONTENTS ===" | Add-Content $out
$wslcfg = "$env:USERPROFILE\.wslconfig"
if (Test-Path $wslcfg) { Get-Content $wslcfg | Add-Content $out } else { "No .wslconfig found" | Add-Content $out }

Write-Host "Done. Output saved to: $out" -ForegroundColor Green
