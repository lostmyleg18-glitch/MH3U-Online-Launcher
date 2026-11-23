# Builds dist\MH3U_Play.exe (one file, no console window).
# Needs 64-bit Python 3.11+ with:  pip install pyinstaller pywebview
#   powershell -ExecutionPolicy Bypass -File launcher\build.ps1 [-Python C:\path\to\python.exe]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$work = Join-Path $env:TEMP "mh3u_play_build"

& $Python (Join-Path $here "mh3u_play.py") --selftest
if ($LASTEXITCODE -ne 0) { throw "self-test failed" }
if (-not (Test-Path (Join-Path $here "mh3u_play.ico"))) { & $Python (Join-Path $here "make_icon.py") (Join-Path $here "mh3u_play.ico") }

# Optional own background art: ui\background.jpg or ui\background.png is bundled when present.
$art = @()
foreach ($name in 'background.jpg', 'background.png') {
  $p = Join-Path $here "ui\$name"
  if (Test-Path $p) { $art += '--add-data', "$p;ui" }
}
# The server's address: launcher\server.txt, one line (see server.txt.example). Not on GitHub.
$server = Join-Path $here "server.txt"
if (Test-Path $server) { $art += '--add-data', "$server;." }
else { Write-Warning "launcher\server.txt is missing: this MH3U_Play.exe won't know which server to use." }
# The game client with the sound fix (see cemu_soundfix\README.txt), bundled when present.
$fix = Join-Path $here "cemu_soundfix"
foreach ($name in 'Cemu_release.exe', 'soundfix.json') {
  $p = Join-Path $fix $name
  if (Test-Path $p) { $art += '--add-data', "$p;cemu_soundfix" }
}

& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name MH3U_Play `
  --icon (Join-Path $here "mh3u_play.ico") `
  --add-data "$(Join-Path $here 'ui\index.html');ui" `
  --add-data "$(Join-Path $here 'ui\Cinzel.ttf');ui" `
  --add-data "$(Join-Path $here 'mh3u_play.ico');." `
  --add-binary "$(Join-Path $here 'SDL3.dll');." `
  @art `
  --distpath (Join-Path $root "dist") --workpath $work --specpath $work `
  (Join-Path $here "mh3u_play.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built: $(Join-Path $root 'dist\MH3U_Play.exe')"
