<# : MH3U Online - one-click server setup for a Windows VPS (this file is a .bat and a PowerShell script)
@echo off
setlocal
net session >nul 2>&1
if errorlevel 1 (
  echo Asking for administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "MH3U_SETUP_FILE=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression ([IO.File]::ReadAllText($env:MH3U_SETUP_FILE))"
echo.
pause
exit /b
#>

# ============================================================================ settings
$PublicIP   = ''      # the VPS's public IPv4 (what players' games connect to). Empty: taken from the existing server settings, or asked for
$ServerName = 'MH3U Online'
$Dir        = 'C:\MH3U-Server'
$TaskName   = 'MH3U Server'
$Repo       = 'Matt-Wood-23/mh3u-revival'
$UdpPorts   = @('1223-1224', '10025', '27100-27387')
# Install the newest release even when it's marked as a test (pre-)release. v0.3.0-beta is one,
# and it's the first with named halls and the admin dashboard; the older stable v0.2.1-beta has
# a single hall and no dashboard. Set to $false to stay on stable releases only.
$Prerelease = $true
# Gathering halls players pick from in game, comma-separated, and hunters per hall. 15 halls is
# the server's maximum. Each hall lists only the rooms made in it. A hunt itself stays at 4, the
# game's own limit. Names are cut to 24 characters.
$HallNames  = 'Low Rank 1,Low Rank 2,Low Rank 3,Low Rank 4,Low Rank 5,' +
              'High Rank 1,High Rank 2,High Rank 3,High Rank 4,High Rank 5,' +
              'G Rank 1,G Rank 2,G Rank 3,G Rank 4,G Rank 5'
$HallMax    = 32
# The halls an earlier version of this setup wrote. Found unchanged, they become $HallNames.
$OldHallNames = 'Low Rank,High Rank,G Rank'

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say([string]$t) { Write-Host ''; Write-Host "== $t" -ForegroundColor Yellow }
function Ok([string]$t) { Write-Host "   $t" -ForegroundColor Green }
function Warn([string]$t) { Write-Host "   $t" -ForegroundColor DarkYellow }

function Test-NatCheck([string]$ip) {
    # The game's first online step: "what address do you see me at?" on UDP 10025.
    $udp = New-Object Net.Sockets.UdpClient
    $udp.Client.ReceiveTimeout = 2000
    try {
        $pkt = [byte[]](0,0,0,0x65, 0,0,0,0, 0,0,0,0, 0,0,0,0)
        [void]$udp.Send($pkt, $pkt.Length, $ip, 10025)
        $ep = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
        return ($udp.Receive([ref]$ep).Length -ge 16)
    } catch { return $false } finally { $udp.Close() }
}

function Stop-MH3UServer {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-Process -Name server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Dir\*" } | Stop-Process -Force
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*run-server.ps1*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

function Get-MH3URelease {
    # Newest release that has the bundle. GitHub's "latest" skips pre-releases, so list them instead.
    $hdr = @{ 'User-Agent' = 'MH3U-Server-Setup' }
    if (-not $Prerelease) { return Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers $hdr }
    $all = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases?per_page=20" -Headers $hdr
    # Piped from a variable so Windows PowerShell 5.1 walks the list item by item.
    $all | Where-Object { -not $_.draft -and ($_.assets | Where-Object { $_.name -eq 'MH3U_Online_Bundle.zip' }) } |
        Sort-Object { [datetime]$_.published_at } -Descending | Select-Object -First 1
}

function Add-MissingSettings([string]$Path) {
    # Settings this setup learned after your server-settings.txt was made: added once. Your own
    # values are never changed; only the halls an earlier setup wrote, if still as it wrote them.
    $lines = @(Get-Content $Path -ErrorAction SilentlyContinue)
    $old = "MH3U_HALL_NAMES=$OldHallNames"
    if ($lines -ccontains $old) {
        $lines = @($lines | ForEach-Object { if ($_ -ceq $old) { "MH3U_HALL_NAMES=$HallNames" } else { $_ } })
        Set-Content -Path $Path -Value $lines -Encoding ASCII
        Ok "Changed in your settings: MH3U_HALL_NAMES=$HallNames"
    }
    $text = $lines -join "`n"
    $new = @()
    if ($text -notmatch '(?m)^\s*MH3U_(HALL_NAMES|NUM_WORLDS)\s*=') {
        $new += '# Gathering halls players pick from in game (up to 15), comma-separated. Each hall'
        $new += '# lists only the rooms made in it. Needs server v0.3.0-beta or newer.'
        $new += "MH3U_HALL_NAMES=$HallNames"
    }
    if ($text -notmatch '(?m)^\s*MH3U_HALL_MAX\s*=') {
        $new += '# Hunters per hall (default 16). A hunt itself stays at 4, the game''s own limit.'
        $new += "MH3U_HALL_MAX=$HallMax"
    }
    if ($new) { Add-Content -Path $Path -Value $new -Encoding ASCII }
    return ($new | Where-Object { $_ -match '^MH3U_' })
}

function Get-SavedPublicIP {
    $settings = Join-Path $Dir 'server-settings.txt'
    Get-Content $settings -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_ -match '^\s*MH3U_ADVERTISE\s*=\s*(\S+)') { $Matches[1] } } | Select-Object -First 1
}

function Resolve-PublicIP {
    # $PublicIP at the top, else the address in the existing server settings, else ask.
    if ($PublicIP) { return $PublicIP }
    $saved = Get-SavedPublicIP
    if ($saved) { return $saved }
    $guess = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' } |
        Select-Object -First 1 -ExpandProperty IPAddress
    $prompt = '   Public IPv4 address of this VPS (players connect to it)'
    if ($guess) { $prompt += " [$guess]" }
    $ip = (Read-Host $prompt).Trim()
    if (-not $ip) { $ip = $guess }
    if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "That isn't an IPv4 address: '$ip'" }
    return $ip
}

function Install-MH3UServer {
    $PublicIP = Resolve-PublicIP
    Say 'Downloading the latest MH3U Revival server'
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    $rel = Get-MH3URelease
    if (-not $rel) { throw 'No MH3U Revival release with MH3U_Online_Bundle.zip was found.' }
    $asset = $rel.assets | Where-Object { $_.name -eq 'MH3U_Online_Bundle.zip' } | Select-Object -First 1
    if (-not $asset) { throw 'The release has no MH3U_Online_Bundle.zip.' }
    $zipPath = Join-Path $Dir 'download.zip'
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Ok "Got $($rel.tag_name)"

    Say 'Installing server.exe'
    Stop-MH3UServer
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq 'server.exe' } | Select-Object -First 1
        if (-not $entry) { throw 'server.exe is missing from the download.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $Dir 'server.exe'), $true)
    } finally { $zip.Dispose() }
    Remove-Item $zipPath -Force
    Set-Content -Path (Join-Path $Dir 'version.txt') -Value $rel.tag_name -Encoding ASCII
    Ok "$Dir\server.exe"

    $settings = Join-Path $Dir 'server-settings.txt'
    if (-not (Test-Path $settings)) {
        @(
            '# MH3U server settings. After editing, run MH3U_Server_Setup.bat again (option 1).',
            '# Every MH3U_* option of MH3U Revival works here (see its docs/HOSTING.md).',
            "MH3U_ADVERTISE=$PublicIP",
            '# force = all hunt traffic goes through this server: players need no port forwarding',
            '# and never see each other''s IP addresses.',
            'MH3U_RELAY=force',
            '# 0 = no public status page, so nobody can read player counts from outside.',
            'MH3U_STATUS_PORT=0',
            '# Admin dashboard (who is online, announcements, safe restarts). Only reachable on',
            '# this VPS itself: open http://127.0.0.1:8081/ in a browser here.',
            'MH3U_ADMIN_PORT=8081',
            "MH3U_SERVER_NAME=$ServerName",
            "MH3U_LOG_FILE=$Dir\server.log"
        ) | Set-Content -Path $settings -Encoding ASCII
        Ok "Settings: $settings"
    } else {
        Ok "Keeping your settings: $settings"
    }
    foreach ($line in Add-MissingSettings $settings) { Ok "Added to your settings: $line" }

    @'
# Started by the "MH3U Server" scheduled task. Restarts server.exe if it ever stops.
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Dir
while ($true) {
    foreach ($line in Get-Content (Join-Path $Dir 'server-settings.txt')) {
        if ($line -match '^\s*(MH3U_[A-Z0-9_]+)\s*=\s*(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim() }
    }
    Add-Content (Join-Path $Dir 'restarts.log') ('{0}  starting server' -f (Get-Date -Format s))
    $p = Start-Process -FilePath (Join-Path $Dir 'server.exe') -WorkingDirectory $Dir -NoNewWindow -PassThru -Wait
    Add-Content (Join-Path $Dir 'restarts.log') ('{0}  server stopped (code {1}), restarting in 5 s' -f (Get-Date -Format s), $p.ExitCode)
    Start-Sleep -Seconds 5
}
'@ | Set-Content -Path (Join-Path $Dir 'run-server.ps1') -Encoding UTF8

    Say 'Opening the Windows Firewall'
    Get-NetFirewallRule -DisplayName 'MH3U Server*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName 'MH3U Server (game, UDP)' -Direction Inbound -Action Allow -Protocol UDP `
        -LocalPort $UdpPorts -Profile Any | Out-Null
    Ok ('UDP ' + ($UdpPorts -join ', ') + ' open')

    Say 'Running the server in the background (starts with Windows, restarts after crashes)'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Dir\run-server.ps1`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $taskSettings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Ok "Scheduled task '$TaskName' started"

    Say 'Checking that the server answers'
    $up = $false
    for ($i = 0; $i -lt 20 -and -not $up; $i++) { Start-Sleep -Seconds 2; $up = Test-NatCheck '127.0.0.1' }
    if ($up) { Ok 'The server is running and answering.' }
    else { Warn "No answer yet. Look at $Dir\server.log and $Dir\restarts.log (an antivirus may have blocked server.exe)." }

    $desk = [Environment]::GetFolderPath('CommonDesktopDirectory')
    Set-Content -Path (Join-Path $desk 'MH3U Server dashboard.url') -Value "[InternetShortcut]`r`nURL=http://127.0.0.1:8081/" -Encoding ASCII
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $desk 'MH3U Server folder.lnk')); $lnk.TargetPath = $Dir; $lnk.Save()

    Say 'Done'
    Write-Host "   Players connect to $PublicIP with the MH3U Online launcher (MH3U_Play.exe)."
    Write-Host '   Dashboard on this VPS: desktop shortcut "MH3U Server dashboard" (who is online, announcements, restarts).'
    Write-Host ''
    Warn 'If your VPS provider has its own firewall in its web panel, open these there too:'
    Warn ('   UDP ' + ($UdpPorts -join ', ') + ', inbound, from anywhere.')
    Write-Host '   To update the server later, just run this file again.'
}

function Show-MH3UStatus {
    Say 'Status'
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { Warn 'Not installed.'; return }
    Write-Host "   Task: $($task.State)"
    $proc = Get-Process -Name server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Dir\*" }
    Write-Host ('   server.exe: ' + $(if ($proc) { "running (PID $($proc.Id))" } else { 'not running' }))
    Write-Host ('   Version: ' + (Get-Content (Join-Path $Dir 'version.txt') -ErrorAction SilentlyContinue))
    if (Test-NatCheck '127.0.0.1') { Ok 'Answering on UDP 10025.' } else { Warn 'Not answering on UDP 10025.' }
    $log = Join-Path $Dir 'server.log'
    if (Test-Path $log) { Say 'Last lines of server.log'; Get-Content $log -Tail 15 | ForEach-Object { Write-Host "   $_" } }
}

function Uninstall-MH3UServer {
    Say 'Removing the MH3U server'
    Stop-MH3UServer
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetFirewallRule -DisplayName 'MH3U Server*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $desk = [Environment]::GetFolderPath('CommonDesktopDirectory')
    Remove-Item (Join-Path $desk 'MH3U Server dashboard.url'), (Join-Path $desk 'MH3U Server folder.lnk') -ErrorAction SilentlyContinue
    Ok 'Task, firewall rule and shortcuts removed.'
    if ((Read-Host "   Also delete $Dir (settings and logs)? y/N") -match '^[yY]') {
        Remove-Item -Recurse -Force $Dir; Ok "$Dir deleted."
    } else { Ok "$Dir kept." }
}

Write-Host ''
Write-Host '  MH3U ONLINE - server setup' -ForegroundColor Yellow
$shownIP = if ($PublicIP) { $PublicIP } else { Get-SavedPublicIP }
Write-Host ('  Server address: ' + $(if ($shownIP) { $shownIP } else { 'asked for when installing' }))
Write-Host ''
Write-Host '  [1] Install or update the server  (default)'
Write-Host '  [2] Show status'
Write-Host '  [3] Uninstall'
$choice = Read-Host '  Choose 1, 2 or 3 and press Enter'
try {
    switch ($choice) {
        '2' { Show-MH3UStatus }
        '3' { Uninstall-MH3UServer }
        default { Install-MH3UServer }
    }
} catch {
    Write-Host ''
    Write-Host "  Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
}
