#Requires -Version 5.1
<#
.SYNOPSIS
    BigRock App — SD Card Preparation Script
    
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
        * WiFi: leave blank — the BigRock portal will handle this on first boot
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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

$candidates = Get-Volume | Where-Object {
    $_.DriveType -eq 'Removable' -and
    $_.FileSystem -eq 'FAT32' -and
    ($_.FileSystemLabel -match 'boot' -or $_.Size -lt 600MB)
}

if ($candidates.Count -eq 0) {
    # Also check fixed disks in case SD reader shows as fixed
    $candidates = Get-Volume | Where-Object {
        $_.FileSystem -eq 'FAT32' -and
        $_.Size -lt 600MB -and
        $_.DriveLetter -ne $null
    }
}

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
    $drive = "$($vol.DriveLetter):"
    Write-Host "Found boot partition: $drive  ($($vol.FileSystemLabel), $([math]::Round($vol.Size/1MB))MB)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Multiple FAT32 partitions found. Select your SD card boot partition:" -ForegroundColor Yellow
    $i = 1
    foreach ($v in $candidates) {
        Write-Host "  [$i] $($v.DriveLetter):  $($v.FileSystemLabel)  $([math]::Round($v.Size/1MB))MB"
        $i++
    }
    $sel = Read-Host "Enter number"
    $vol  = $candidates[[int]$sel - 1]
    $drive = "$($vol.DriveLetter):"
}

# Sanity check — must have cmdline.txt
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
    # Ensure Unix line endings (LF only) — critical for bash
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
# Patch cmdline.txt — add firstrun trigger (only if not already present)
# ---------------------------------------------------------------------------
Write-Host "Patching cmdline.txt..." -ForegroundColor Cyan
$cmdline = [System.IO.File]::ReadAllText($cmdlineFile).Trim()

if ($cmdline -match "systemd\.run=") {
    Write-Host "  cmdline.txt already patched — skipping." -ForegroundColor Yellow
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
Write-Host "  4. After install, if no WiFi is configured, a hotspot"
Write-Host "     named 'BigRock-Setup' (password: bigrock1234) will appear"
Write-Host "  5. Connect to it and visit http://10.42.0.1 to set your WiFi"
Write-Host "  6. The Pi reboots into the BigRock kiosk app"
Write-Host ""
Write-Host "Log file (after boot): /boot/firmware/bigrock-firstrun.log" -ForegroundColor Gray
Write-Host ""
