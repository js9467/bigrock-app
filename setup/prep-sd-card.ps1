#Requires -Version 5.1
<#
.SYNOPSIS
    BigRock App - SD Card Preparation Script
    
.DESCRIPTION
    Run this AFTER flashing Raspberry Pi OS Lite to your SD card with
    Raspberry Pi Imager. It:
      1. Finds the boot (FAT32) partition of the SD card
      2. Copies firstrun.sh to it
      3. Patches cmdline.txt so the Pi auto-installs the app on first boot
    
.USAGE
    Open PowerShell and run:
        .\setup\prep-sd-card.ps1
    
    When prompted, choose the drive letter of your SD card's boot partition.
    
.NOTES
    - The SD card must already be flashed with Raspberry Pi OS Lite (64-bit, Bookworm)
      using Raspberry Pi Imager: https://www.raspberrypi.com/software/
    - In Imager's "OS Customization" screen, set:
        * Hostname: bigrock-1  (or bigrock-2, bigrock-3, etc.)
        * Username: pi
        * Password: (your chosen password)
        * Enable SSH (password auth)
        * WiFi: leave blank - the BigRock portal will handle this on first boot
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Self-elevate to Administrator if not already running as admin
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $psArgs -Wait
    exit
}

$RepoUrl    = "https://github.com/js9467/bigrock-app"
$FirstRunUrl = "https://raw.githubusercontent.com/js9467/bigrock-app/main/setup/firstrun.sh"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  BigRock SD Card Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script prepares your SD card so the Pi installs" -ForegroundColor White
Write-Host "the BigRock app automatically on first boot." -ForegroundColor White
Write-Host ""
Write-Host "BEFORE running this script:" -ForegroundColor Yellow
Write-Host "  1. Flash 'Raspberry Pi OS Lite (64-bit)' with Raspberry Pi Imager"
Write-Host "  2. In Imager's customization screen, set hostname/username/password/SSH"
Write-Host "  3. Eject and re-insert the SD card (so Windows sees the boot partition)"
Write-Host ""

# ---------------------------------------------------------------------------
# Find the SD card boot partition
# ---------------------------------------------------------------------------
Write-Host "Scanning for SD card boot partition (FAT32 volume named 'bootfs' or 'boot')..." -ForegroundColor Cyan

$candidates = @(Get-Volume | Where-Object {
    $_.FileSystem -eq 'FAT32' -and
    ($_.FileSystemLabel -match 'boot' -or $_.Size -lt 600MB)
})

if ($candidates.Count -eq 0) {
    Write-Host ""
    Write-Host "ERROR: No FAT32 boot partition found." -ForegroundColor Red
    Write-Host "Make sure the SD card is inserted and visible in Windows Explorer."
    Write-Host "You can specify the drive letter manually by running:"
    Write-Host "  .\setup\prep-sd-card.ps1 -DriveLetter E"
    exit 1
}

if ($candidates.Count -eq 1) {
    $vol = $candidates[0]
} else {
    Write-Host ""
    Write-Host "Multiple FAT32 partitions found. Select your SD card boot partition:" -ForegroundColor Yellow
    $i = 1
    foreach ($v in $candidates) {
        $lbl = if ($v.DriveLetter) { "$($v.DriveLetter):" } else { "(no letter)" }
        Write-Host "  [$i] $lbl  $($v.FileSystemLabel)  $([math]::Round($v.Size/1MB))MB"
        $i++
    }
    $sel = Read-Host "Enter number"
    $vol = $candidates[[int]$sel - 1]
}

# Auto-assign a drive letter if the volume doesn't have one
$_assignedLetter = $false
if (-not $vol.DriveLetter) {
    Write-Host "  Volume has no drive letter - assigning one automatically..." -ForegroundColor Yellow
    # Find first free letter from E onwards
    $used = (Get-PSDrive -PSProvider FileSystem).Name
    $freeLetter = ('E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T') |
                  Where-Object { $used -notcontains $_ } |
                  Select-Object -First 1
    if (-not $freeLetter) {
        Write-Host "ERROR: No free drive letters available." -ForegroundColor Red
        exit 1
    }
    try {
        $partition = Get-Partition | Where-Object {
            $_.Size -ge ($vol.Size - 20MB) -and $_.Size -le ($vol.Size + 20MB) -and $_.DiskNumber -ge 1
        } | Select-Object -First 1
        Set-Partition -DiskNumber $partition.DiskNumber -PartitionNumber $partition.PartitionNumber -NewDriveLetter $freeLetter
        Start-Sleep -Seconds 2
        # Re-fetch the volume to get updated drive letter
        $vol = Get-Volume -DriveLetter $freeLetter
        $_assignedLetter = $true
        Write-Host "  Assigned drive letter $freeLetter`:" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Could not assign drive letter automatically: $_" -ForegroundColor Red
        Write-Host "Open Disk Management, right-click the bootfs partition, choose"
        Write-Host "'Change Drive Letter and Paths', add a letter, then re-run this script."
        exit 1
    }
}

$drive = "$($vol.DriveLetter):"
Write-Host "Found boot partition: $drive  ($($vol.FileSystemLabel), $([math]::Round($vol.Size/1MB))MB)" -ForegroundColor Green

# Sanity check - must have cmdline.txt
$cmdlineFile = Join-Path $drive "cmdline.txt"
if (-not (Test-Path $cmdlineFile)) {
    Write-Host "ERROR: $cmdlineFile not found. This doesn't look like a Pi boot partition." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Get firstrun.sh (from local repo or download from GitHub)
# ---------------------------------------------------------------------------
$localFirstrun = Join-Path $ScriptDir "firstrun.sh"
$destFirstrun  = Join-Path $drive "firstrun.sh"

if (Test-Path $localFirstrun) {
    Write-Host "Copying firstrun.sh from local repo..." -ForegroundColor Cyan
    # Ensure Unix line endings (LF only) - critical for bash
    $content = [System.IO.File]::ReadAllText($localFirstrun) -replace "`r`n", "`n" -replace "`r", "`n"
    [System.IO.File]::WriteAllText($destFirstrun, $content, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Host "Downloading firstrun.sh from GitHub..." -ForegroundColor Cyan
    try {
        $content = (Invoke-WebRequest -Uri $FirstRunUrl -UseBasicParsing).Content
        $content = $content -replace "`r`n", "`n" -replace "`r", "`n"
        [System.IO.File]::WriteAllText($destFirstrun, $content, [System.Text.UTF8Encoding]::new($false))
    } catch {
        Write-Host "ERROR: Could not download firstrun.sh: $_" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  -> $destFirstrun" -ForegroundColor Green

# ---------------------------------------------------------------------------
# Patch cmdline.txt - add firstrun trigger (only if not already present)
# ---------------------------------------------------------------------------
Write-Host "Patching cmdline.txt..." -ForegroundColor Cyan
$cmdline = [System.IO.File]::ReadAllText($cmdlineFile).Trim()

if ($cmdline -match "systemd\.run=") {
    Write-Host "  cmdline.txt already patched - skipping." -ForegroundColor Yellow
} else {
    $injection = " systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target"
    $newCmdline = $cmdline + $injection
    # Write back with Unix LF and NO BOM
    [System.IO.File]::WriteAllText($cmdlineFile, $newCmdline + "`n", [System.Text.UTF8Encoding]::new($false))
    Write-Host "  -> cmdline.txt patched." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  SD Card is ready!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Safely eject the SD card from Windows"
Write-Host "  2. Insert it into the Raspberry Pi and power on"
Write-Host "  3. The Pi will auto-install everything (takes ~5-10 min)"
Write-Host "     You can monitor progress via SSH or a connected monitor"
Write-Host "  4. After install, if no WiFi is configured, an OPEN hotspot"
Write-Host "     named 'BigRock-Setup' will appear (no password needed)"
Write-Host "  5. Connect to it - a setup page will pop up automatically"
Write-Host "  6. Enter your WiFi credentials and the Pi reboots into the kiosk"
Write-Host ""
Write-Host "Log file (after boot): /boot/firmware/bigrock-firstrun.log" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to close"
