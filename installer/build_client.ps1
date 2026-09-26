# Đóng gói Auto_veo3 thành thư mục chạy được ngay + file zip. Chạy:  powershell -File installer\build_client.ps1
# Kết quả: dist\Auto_veo3\  và  dist\Auto_veo3-<ver>-win64.zip  (+ SHA256.txt)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$ver = (& $py -c "import sys; sys.path.insert(0,'client'); from autoveo import config; print(config.VERSION)").Trim()

# ffmpeg đóng kèm (đặt ở client\vendor\ffmpeg\ffmpeg.exe; nếu chưa có thì chép từ máy build)
$ff = Join-Path $root "client\vendor\ffmpeg\ffmpeg.exe"
if (-not (Test-Path $ff)) {
    $src = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if (-not $src) { throw "Không tìm thấy ffmpeg.exe. Chép vào client\vendor\ffmpeg\ffmpeg.exe rồi chạy lại." }
    New-Item -ItemType Directory -Force (Split-Path $ff) | Out-Null
    Copy-Item $src $ff
}

if (-not (Test-Path "client\resources\logo.png")) { & $py tools\make_logo.py }

Remove-Item -Recurse -Force build, dist\Auto_veo3 -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --name Auto_veo3 --windowed `
    --icon "$root\client\resources\app.ico" --paths "$root\client" `
    --add-data "$root\client\resources;resources" `
    --add-binary "${ff};ffmpeg" `
    --exclude-module tkinter --exclude-module unittest --exclude-module pytest `
    --distpath dist --workpath build\client --specpath build `
    "$root\client\autoveo_entry.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller lỗi" }

# tài liệu đi kèm
Copy-Item installer\HUONG-DAN.txt dist\Auto_veo3\HUONG-DAN.txt
Copy-Item installer\THIRD-PARTY.txt dist\Auto_veo3\THIRD-PARTY.txt

$zip = "dist\Auto_veo3-$ver-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path dist\Auto_veo3 -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Out-File dist\SHA256.txt -Encoding ascii
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "XONG: $zip ($mb MB)  SHA256=$hash"
