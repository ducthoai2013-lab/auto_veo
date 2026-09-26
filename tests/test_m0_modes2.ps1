# M0.2b - test 2 mode con lai: start_end_image + components (@tag). Chay sau khi test_m0_modes.ps1 PASS.
#   powershell -ExecutionPolicy Bypass -File D:\claude\app_b1\Auto_veo\tests\test_m0_modes2.ps1
# Doc khoa G-Labs tu D:\GatewayData\config.json (giong test_m0_modes.ps1). Moi video that ton 1 luot credit Veo.
$cfg = Get-Content "D:\GatewayData\config.json" -Raw | ConvertFrom-Json
$ApiKey = ($cfg.glabs_api_key -replace "\s", "")
$Base = "http://127.0.0.1:8765"
$outDir = "D:\GatewayData\test_output"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$headers = @{ "X-API-Key" = $ApiKey; "Content-Type" = "application/json" }

try { Invoke-RestMethod -Uri "$Base/api/health" -TimeoutSec 5 | Out-Null; Write-Host "Ket noi G-Labs Health: OK" -ForegroundColor Green }
catch { Write-Host "Loi: Khong the ket noi G-Labs tai $Base" -ForegroundColor Red; exit 1 }

function Run-Task($endpoint, $bodyObj, $outFile) {
    Write-Host "Dang gui task: $outFile ..." -ForegroundColor Cyan
    $resp = Invoke-RestMethod -Uri "$Base$endpoint" -Method POST -Headers $headers -Body ($bodyObj | ConvertTo-Json -Depth 6)
    $taskId = $resp.task_id
    if (-not $taskId) { throw "Khong nhan duoc task_id tu G-Labs" }
    Write-Host "-> Task ID: $taskId. Dang cho xu ly..." -ForegroundColor Gray
    $elapsed = 0
    while ($elapsed -lt 420) {
        Start-Sleep -Seconds 5; $elapsed += 5
        $sj = Invoke-RestMethod -Uri "$Base/api/status/$taskId" -Method GET -Headers $headers
        Write-Host "Task $taskId : $($sj.status) ($($elapsed)s)"
        if ($sj.status -eq "completed") {
            Invoke-WebRequest -Uri $sj.results[0] -Headers $headers -OutFile "$outDir\$outFile" -UseBasicParsing
            Write-Host "-> Thanh cong: $outDir\$outFile" -ForegroundColor Green
            return "$outDir\$outFile"
        }
        if ($sj.status -eq "failed") { throw "Task $taskId that bai: $($sj.error)" }
    }
    throw "Timeout khi cho task: $outFile"
}
function To-DataUri($path) { "data:image/jpeg;base64," + [Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) }
function Probe($path) {
    if (Get-Command ffprobe -ErrorAction SilentlyContinue) {
        $j = & ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,duration -of json $path | ConvertFrom-Json
        $s = $j.streams[0]; Write-Host "   ffprobe: $($s.codec_name) $($s.width)x$($s.height) $([math]::Round([double]$s.duration,1))s" -ForegroundColor Gray
    }
}

# Anh dau = 01_cube.jpg (da co tu M0.2); tao them anh cuoi
$startImg = "$outDir\01_cube.jpg"
if (-not (Test-Path $startImg)) { throw "Chua co $startImg - chay test_m0_modes.ps1 truoc" }
$endImg = Run-Task "/api/image/generate" @{ prompt = "a simple wooden cube tilted 45 degrees on white background"; model = "nano_banana_2"; aspect_ratio = "16:9" } "04_cube_end.jpg"

# Test 4: start_end_image (thu tu bat buoc: [0]=dau, [1]=cuoi)
$v3 = Run-Task "/api/video/generate" @{
    prompt = "the wooden cube smoothly tilts from flat to 45 degrees, no text overlay"
    mode = "start_end_image"
    reference_images = @((To-DataUri $startImg), (To-DataUri $endImg))
    resolution = @("720p")
} "05_start_end.mp4"
Probe $v3

# Test 5: components (@tag) - tao nhan vat roi dung @robotguy trong prompt
$charImg = Run-Task "/api/image/generate" @{ prompt = "a friendly cartoon robot character, full body, standing, plain white background"; model = "nano_banana_2"; aspect_ratio = "16:9" } "06_robot.jpg"
$v4 = Run-Task "/api/video/generate" @{
    prompt = "the @robotguy waves at the camera and smiles, no text overlay"
    mode = "components"
    reference_images = @(@{ data = (To-DataUri $charImg); name = "robotguy.jpg" })
    resolution = @("720p")
} "07_components.mp4"
Probe $v4

Write-Host "`n>>> KET QUA: PASS TEST M0.2b (start_end_image + components) <<<" -ForegroundColor Green
Write-Host "Mo 05_start_end.mp4 va 07_components.mp4 xem bang mat: khung dau/cuoi dung? robot con giong anh 06_robot.jpg?"
