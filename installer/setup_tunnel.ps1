# Cài Cloudflare Tunnel cho veo.d100radar.com trên MÁY NHÀ. Tự xin quyền admin (bấm Yes ở hộp thoại UAC).
#   powershell -ExecutionPolicy Bypass -File installer\setup_tunnel.ps1
# Tunnel Token được hỏi bằng ô nhập ẩn trong cửa sổ admin này. KHÔNG gửi token vào chat, KHÔNG lưu vào file/repo.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Cần quyền admin để cài dịch vụ. Đang mở cửa sổ admin..." -ForegroundColor Cyan
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit 0
}
$src = Join-Path $root "tools\cloudflared\cloudflared.exe"
if (-not (Test-Path $src)) { throw "Thiếu $src" }
$dir = "C:\Program Files\cloudflared"
New-Item -ItemType Directory -Force $dir | Out-Null
$exe = Join-Path $dir "cloudflared.exe"
Copy-Item $src $exe -Force

$existing = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Đã có dịch vụ cloudflared ($($existing.Status))." -ForegroundColor Yellow
    $ans = Read-Host "Cài lại với token mới? (y/N)"
    if ($ans -ne "y") { Write-Host "Giữ nguyên."; exit 0 }
    & $exe service uninstall | Out-Null
}
Write-Host ""
Write-Host "Dán Tunnel Token (chuỗi dài bắt đầu bằng 'eyJ...' trong trang tạo tunnel của Cloudflare). Ô nhập ẩn." -ForegroundColor Cyan
$sec = Read-Host "Tunnel Token" -AsSecureString
$token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
if ($token -match "^cloudflared\s+service\s+install\s+(.+)$") { $token = $Matches[1].Trim() }     # lỡ dán cả lệnh
if ($token.Length -lt 60) { throw "Token quá ngắn, có vẻ chưa dán đúng." }
& $exe service install $token
if ($LASTEXITCODE -ne 0) { throw "cloudflared service install lỗi" }
Start-Service cloudflared -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
Get-Service cloudflared | Format-Table Name, Status -AutoSize
Write-Host "Xong. Quay lại chat báo 'tunnel xong' để tôi kiểm tra https://veo.d100radar.com/v1/health" -ForegroundColor Green
