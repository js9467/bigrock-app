#Requires -Version 5.1
<#
.SYNOPSIS
    BigRock App - Create distributable SD card image

.DESCRIPTION
    Reads the SD card (after running sysprep.sh on the master Pi) and saves
    a compressed .img.gz file you can flash to any 32GB+ card with
    Raspberry Pi Imager (Choose OS -> Use custom -> select the .img.gz).

.USAGE
    Double-click "Create Image.bat"  OR  run in PowerShell:
        .\setup\"Create Image.ps1"
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Self-elevate to Administrator if needed
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`""
    Start-Process powershell -Verb RunAs -ArgumentList $psArgs -Wait
    exit
}

Add-Type -AssemblyName System.IO.Compression

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  BigRock SD Card Image Creator" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This reads the master SD card and saves a compressed image." -ForegroundColor White
Write-Host "Make sure you ran sysprep.sh on the Pi first, and the Pi is powered off." -ForegroundColor Yellow
Write-Host ""

# ---------------------------------------------------------------------------
# Find the SD card (removable disk >= 28GB, the Pi card)
# ---------------------------------------------------------------------------
Write-Host "Scanning for SD card..." -ForegroundColor Cyan

$candidates = @(Get-Disk | Where-Object {
    $_.BusType -in @('SD', 'USB') -or $_.Path -match 'Removable'
} | Where-Object { $_.Size -ge 28GB })

if ($candidates.Count -eq 0) {
    # Broader search - any non-system disk >= 28GB
    $candidates = @(Get-Disk | Where-Object {
        -not $_.IsSystem -and -not $_.IsBoot -and $_.Size -ge 28GB
    })
}

if ($candidates.Count -eq 0) {
    Write-Host ""
    Write-Host "ERROR: No SD card found." -ForegroundColor Red
    Write-Host "Make sure the card is inserted and Windows can see it."
    Read-Host "Press Enter to exit"
    exit 1
}

$disk = $null
if ($candidates.Count -eq 1) {
    $disk = $candidates[0]
    Write-Host "Found: Disk $($disk.Number) - $($disk.FriendlyName) ($([math]::Round($disk.Size/1GB, 1)) GB)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Multiple disks found. Select the SD card:" -ForegroundColor Yellow
    $i = 1
    foreach ($d in $candidates) {
        Write-Host "  [$i] Disk $($d.Number) - $($d.FriendlyName) ($([math]::Round($d.Size/1GB,1)) GB)"
        $i++
    }
    $sel = Read-Host "Enter number"
    $disk = $candidates[[int]$sel - 1]
}

Write-Host ""
Write-Host "WARNING: This will read ALL $([math]::Round($disk.Size/1GB,1)) GB from Disk $($disk.Number)." -ForegroundColor Yellow
Write-Host "Estimated compressed size: 3-8 GB.  Estimated time: 10-30 minutes." -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "Type YES to continue"
if ($confirm -ne "YES") {
    Write-Host "Cancelled." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 0
}

# ---------------------------------------------------------------------------
# Choose output file location
# ---------------------------------------------------------------------------
$defaultOut = Join-Path ([Environment]::GetFolderPath('Desktop')) "bigrock-master.img.gz"
Write-Host ""
Write-Host "Output file [default: $defaultOut]:" -ForegroundColor Cyan
$outPath = Read-Host "Press Enter to use default, or type a path"
if ([string]::IsNullOrWhiteSpace($outPath)) {
    $outPath = $defaultOut
}
if (-not $outPath.EndsWith('.gz')) { $outPath += '.gz' }

# ---------------------------------------------------------------------------
# Read disk and compress to .img.gz
# ---------------------------------------------------------------------------
$diskPath   = "\\.\PhysicalDrive$($disk.Number)"
$totalBytes = $disk.Size
$blockSize  = [long](4 * 1024 * 1024)  # 4 MB chunks

Write-Host ""
Write-Host "Reading Disk $($disk.Number) -> $outPath" -ForegroundColor Cyan
Write-Host "(This window must stay open until complete)" -ForegroundColor Yellow
Write-Host ""

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    $diskStream = [System.IO.File]::Open($diskPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
    $fileStream = [System.IO.File]::Create($outPath)
    $gzipStream = [System.IO.Compression.GZipStream]::new($fileStream, [System.IO.Compression.CompressionLevel]::Optimal)

    $buffer    = New-Object byte[] $blockSize
    $bytesRead = [long]0

    while ($bytesRead -lt $totalBytes) {
        $toRead = [Math]::Min($blockSize, $totalBytes - $bytesRead)
        $read   = $diskStream.Read($buffer, 0, $toRead)
        if ($read -eq 0) { break }
        $gzipStream.Write($buffer, 0, $read)
        $bytesRead += $read

        $pct     = [int]($bytesRead * 100 / $totalBytes)
        $elapsed = $stopwatch.Elapsed.TotalSeconds
        $speed   = if ($elapsed -gt 0) { [math]::Round($bytesRead / $elapsed / 1MB, 1) } else { 0 }
        $gbDone  = [math]::Round($bytesRead / 1GB, 2)
        $gbTotal = [math]::Round($totalBytes / 1GB, 1)
        $outMB   = if (Test-Path $outPath) { [math]::Round((Get-Item $outPath).Length / 1MB) } else { 0 }

        Write-Progress -Activity "Creating image" `
            -Status "$gbDone GB / $gbTotal GB  |  $speed MB/s  |  Compressed: $outMB MB" `
            -PercentComplete $pct
    }

    $gzipStream.Close()
    $fileStream.Close()
    $diskStream.Close()

} catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    try { if (Test-Path $outPath) { Remove-Item $outPath -Force } } catch { }
    Read-Host "Press Enter to exit"
    exit 1
}

$stopwatch.Stop()
$finalSize = [math]::Round((Get-Item $outPath).Length / 1GB, 2)
$minutes   = [math]::Round($stopwatch.Elapsed.TotalMinutes, 1)

Write-Progress -Activity "Creating image" -Completed
Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Image created successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  File:      $outPath" -ForegroundColor White
Write-Host "  Size:      $finalSize GB (compressed)" -ForegroundColor White
Write-Host "  Time:      $minutes minutes" -ForegroundColor White
Write-Host ""
Write-Host "To flash a new card:" -ForegroundColor Cyan
Write-Host "  1. Open Raspberry Pi Imager"
Write-Host "  2. Choose OS -> Use custom -> select the .img.gz above"
Write-Host "  3. Choose your SD card (32GB+)"
Write-Host "  4. Write it"
Write-Host "  5. Insert into Pi and power on"
Write-Host "     - First boot sets a unique hostname (bigrock-XXXXXX)"
Write-Host "     - WiFi portal opens automatically (connect to BigRock-Setup)"
Write-Host "     - App starts and self-updates"
Write-Host ""
Read-Host "Press Enter to close"
