# One-time setup for gta6clip on Windows. Safe to run again. Prints "All set" at the end.
$ErrorActionPreference = "Stop"
$env:UV_LINK_MODE = "copy"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvDir = Join-Path $env:USERPROFILE ".gta6-clipper"
$Venv = Join-Path $EnvDir "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$HomeDir = Join-Path $env:USERPROFILE "gta6-clips"
$script:Missing = $false

function Ok($m)   { Write-Host "[ok] $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "[X]  $m" -ForegroundColor Red; $script:Missing = $true }
function Warn($m) { Write-Host "[!]  $m" -ForegroundColor Yellow }

Write-Host "gta6clip setup"

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    $enc = (& ffmpeg -hide_banner -encoders 2>&1 | Out-String)
    $flt = (& ffmpeg -hide_banner -filters 2>&1 | Out-String)
    if ($enc -match "h264_nvenc") { Ok "ffmpeg h264_nvenc" } else { Bad "ffmpeg has no h264_nvenc encoder" }
    if ($flt -match "\sass\s")    { Ok "ffmpeg libass (ass filter)" } else { Bad "ffmpeg has no libass (ass filter)" }
} else { Bad "ffmpeg missing: winget install Gyan.FFmpeg" }
if (Get-Command claude -ErrorAction SilentlyContinue) { Ok "Claude Code" } else { Bad "claude missing: install Claude Code first" }
if (Get-Command node -ErrorAction SilentlyContinue) { Ok "node (YouTube needs a JS runtime)" } else { Bad "node missing: winget install OpenJS.NodeJS" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Bad "uv missing: winget install astral-sh.uv" }
if ($script:Missing) { Write-Host ""; Write-Host "Fix the [X] lines above, then run this again."; exit 1 }

New-Item -ItemType Directory -Force $EnvDir | Out-Null
if (-not (Test-Path $Py)) {
    & uv venv --python 3.11 $Venv
    if ($LASTEXITCODE) { throw "uv venv failed" }
}
& uv pip install -q --python $Py -U "yt-dlp[default]" faster-whisper nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" "opencv-python-headless<5" pillow numpy soundfile "streamlink>=6" "kokoro>=0.9.4" pip pytest
if ($LASTEXITCODE) { throw "package install failed" }
Ok "Python packages (private env in $Venv)"

# Fonts
$FontDir = Join-Path $Here "fonts"
New-Item -ItemType Directory -Force $FontDir | Out-Null
$fonts = [ordered]@{
    "Montserrat-Black.ttf"  = "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf"
    "Poppins-ExtraBold.ttf" = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-ExtraBold.ttf"
    "Anton-Regular.ttf"     = "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
    "NotoColorEmoji.ttf"    = "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf"
}
foreach ($name in $fonts.Keys) {
    $dest = Join-Path $FontDir $name
    if (-not (Test-Path $dest) -or (Get-Item $dest).Length -eq 0) {
        try { Invoke-WebRequest -UseBasicParsing -Uri $fonts[$name] -OutFile $dest }
        catch { Warn "font download failed: $name"; Remove-Item $dest -ErrorAction SilentlyContinue }
    }
    if (Test-Path $dest) { Ok "font $name" }
}

# YuNet face detector
$Models = Join-Path $EnvDir "models"
New-Item -ItemType Directory -Force $Models | Out-Null
$yunet = Join-Path $Models "yunet.onnx"
if (-not (Test-Path $yunet) -or (Get-Item $yunet).Length -eq 0) {
    try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" -OutFile $yunet }
    catch { Warn "facecam model download failed; clips fall back to a simpler face finder"; Remove-Item $yunet -ErrorAction SilentlyContinue }
}
if (Test-Path $yunet) { Ok "facecam finder (OpenCV YuNet)" }

# Whisper models (cached by huggingface_hub)
$dl = "from faster_whisper.utils import download_model`nfor n in ('small','large-v3-turbo'):`n    download_model(n)`nprint('whisper ok')"
& $Py -c $dl
if ($LASTEXITCODE) { throw "whisper model download failed" }
Ok "Whisper models (small = scan, large-v3-turbo = captions)"

# VoxCPM2 narrator (optional; Kokoro fallback)
$VoxPy = Join-Path $env:APPDATA "OmniVoice\engines\voxcpm2\voxcpm2\.venv\Scripts\python.exe"
$VoxSnap = Join-Path $env:LOCALAPPDATA "OmniVoice\hf_cache\models--openbmb--VoxCPM2\snapshots\32279effe8c19989596f05d353d1447f51d9e915"
if (Test-Path $VoxPy) { Ok "VoxCPM2 python" } else { Warn "VoxCPM2 python not found ($VoxPy); narration falls back to Kokoro" }
if (Test-Path $VoxSnap) { Ok "VoxCPM2 model snapshot" } else { Warn "VoxCPM2 snapshot not found ($VoxSnap); narration falls back to Kokoro" }

# Watchlist
New-Item -ItemType Directory -Force $HomeDir | Out-Null
$wl = Join-Path $HomeDir "streamers.txt"
if (-not (Test-Path $wl)) { Copy-Item (Join-Path $Here "streamers.txt") $wl }
Ok "watchlist: $wl"

Write-Host ""
Write-Host "All set. Try:  gta6clip --find --list"
