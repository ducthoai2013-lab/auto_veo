# Cài Gateway Auto_veo3 trên MÁY NHÀ (nơi chạy G-Labs). Không cần quyền admin.
#   powershell -ExecutionPolicy Bypass -File installer\setup_gateway.ps1
# Việc làm: chép Gateway + khóa công khai vào D:\Auto_veo_Gateway, tạo .env, đăng ký tác vụ tự chạy khi đăng nhập
# Windows, chạy Gateway và kiểm tra. API Key của G-Labs được hỏi bằng ô nhập ẩn (KHÔNG gõ vào chat).
param(
    [string]$InstallDir = "D:\Auto_veo_Gateway",
    [switch]$SkipKeyPrompt,       # không hỏi khóa G-Labs (dùng khi chỉ muốn cài phần còn lại)
    [switch]$ChangeKey,           # hỏi lại khóa dù .env đã có
    [string]$KeyFromJson = ""     # đọc khóa G-Labs từ file JSON có trường glabs_api_key (vd D:\GatewayData\config.json), không cần dán
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist\glabs-gateway"
$pub = Join-Path $root "secrets\veo\veo_public.pem"
if (-not (Test-Path (Join-Path $dist "glabs-gateway.exe"))) { throw "Chưa có $dist. Chạy installer\build_gateway.ps1 trước." }
if (-not (Test-Path $pub)) { throw "Chưa có $pub. Chạy tools\gen_veo_keys.py trước." }

# 1. Dừng HẲN bản đang chạy: tác vụ + vòng lặp start_gateway.bat (nếu không, nó tự bật lại sau 5 giây và khóa DLL)
Stop-ScheduledTask -TaskName "Auto_veo3 Gateway" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "start_gateway\.bat|run_hidden\.vbs" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
for ($i = 0; $i -lt 15; $i++) {
    Get-Process glabs-gateway -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    if (-not (Get-Process glabs-gateway -ErrorAction SilentlyContinue)) { break }
}
New-Item -ItemType Directory -Force $InstallDir | Out-Null
$copied = $false
for ($try = 1; $try -le 5 -and -not $copied; $try++) {
    try { Copy-Item (Join-Path $dist "*") $InstallDir -Recurse -Force -ErrorAction Stop; $copied = $true }
    catch { Write-Host "Chép file lần $try lỗi ($($_.Exception.Message)); thử lại..." -ForegroundColor Yellow; Start-Sleep -Seconds 2
            Get-Process glabs-gateway -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
}
if (-not $copied) { throw "Không chép được Gateway vào $InstallDir (file đang bị khóa)." }
Copy-Item $pub (Join-Path $InstallDir "veo_public.pem") -Force
New-Item -ItemType Directory -Force (Join-Path $InstallDir "data") | Out-Null

# 2. .env (giữ khóa G-Labs cũ nếu đã có)
$envFile = Join-Path $InstallDir ".env"
$oldKey = ""
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^GW_GLABS_KEY=(.*)$' | Select-Object -First 1
    if ($m) { $oldKey = $m.Matches[0].Groups[1].Value.Trim() }
}
$key = $oldKey
if (-not $SkipKeyPrompt -and -not $KeyFromJson -and ($ChangeKey -or -not $oldKey)) {
    Write-Host ""
    Write-Host "Dán API Key của G-Labs (tab 'Webhook API' trong G-Labs). Ô nhập ẩn, không hiện ký tự." -ForegroundColor Cyan
    $sec = Read-Host "G-Labs API Key" -AsSecureString
    $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}
if ($KeyFromJson) {
    if (-not (Test-Path $KeyFromJson)) { throw "Không thấy file $KeyFromJson" }
    $key = [string](Get-Content $KeyFromJson -Raw | ConvertFrom-Json).glabs_api_key
    if (-not $key) { throw "File $KeyFromJson không có trường glabs_api_key" }
}
$key = $key -replace "\s", ""     # khóa copy hay dính dấu cách/xuống dòng -> G-Labs báo 'Invalid or missing API key'
$lines = @(
    "GW_GLABS_URL=http://127.0.0.1:8765",
    "GW_GLABS_KEY=$key",
    "GW_JWT_PUBKEY_FILE=$InstallDir\veo_public.pem",
    "GW_DATA_DIR=$InstallDir\data",
    "GW_RETENTION_DAYS=7",
    "GW_MAX_INFLIGHT_VIDEO=5",
    "GW_MAX_INFLIGHT_IMAGE=8",
    "GW_VIDEO_TIMEOUT=480",
    "GW_POLL_SECONDS=5",
    "GW_PUBLIC_URL=https://veo.d100radar.com",
    "GW_CLIENT_URL=https://d100radar.com/veo3"
)
Set-Content -Path $envFile -Value $lines -Encoding ascii
icacls $envFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null      # chỉ tài khoản này đọc được

# 3. Chạy ẩn + tự chạy khi đăng nhập Windows
$vbs = Join-Path $InstallDir "run_hidden.vbs"
Set-Content -Path $vbs -Encoding ascii -Value ('CreateObject("Wscript.Shell").Run "cmd /c ""' + (Join-Path $InstallDir "start_gateway.bat") + '""", 0, False')
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Auto_veo3 Gateway" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Auto_veo3 Gateway"

# 4. Kiểm tra
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/health" -TimeoutSec 3; $ok = $true; break } catch {}
}
if ($ok) {
    Write-Host "Gateway chạy: ok=$($h.ok) glabs=$($h.glabs) mock=$($h.mock) version=$($h.version)" -ForegroundColor Green
    if (-not $key) { Write-Host "Chưa có API Key G-Labs: chạy lại script này (không kèm -SkipKeyPrompt) để nhập." -ForegroundColor Yellow }
} else { Write-Host "Gateway KHÔNG phản hồi ở 127.0.0.1:8080. Xem cửa sổ start_gateway.bat trong $InstallDir." -ForegroundColor Red; exit 1 }
