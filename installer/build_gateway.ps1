# Đóng gói Gateway cho máy nhà: dist\glabs-gateway\  (glabs-gateway.exe + .env.example + start_gateway.bat)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
Remove-Item -Recurse -Force dist\glabs-gateway -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --name glabs-gateway --console `
    --paths "$root\gateway" `
    --collect-submodules uvicorn --collect-submodules gateway `
    --hidden-import cryptography.hazmat.primitives.asymmetric.ed25519 `
    --exclude-module tkinter --exclude-module PySide6 `
    --distpath dist --workpath build\gateway --specpath build `
    "$root\gateway\gateway_entry.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller lỗi" }
Copy-Item gateway\.env.example dist\glabs-gateway\.env.example
Copy-Item gateway\start_gateway.bat dist\glabs-gateway\start_gateway.bat
Write-Host "XONG: dist\glabs-gateway\"
