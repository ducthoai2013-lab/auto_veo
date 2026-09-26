$cfg = Get-Content "D:\GatewayData\config.json" -Raw | ConvertFrom-Json
$ApiKey = ($cfg.glabs_api_key -replace "[\r\n\t ]", "").Trim()
$Base = "http://127.0.0.1:8765"
$outDir = "D:\GatewayData\test_output"

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

$headers = @{
    "X-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

# Test kết nối health trước
try {
    $h = Invoke-RestMethod -Uri "$Base/api/health" -Method GET -TimeoutSec 5
    Write-Host "Ket noi G-Labs Health: OK" -ForegroundColor Green
} catch {
    Write-Host "Loi: Khong the ket noi G-Labs tai $Base" -ForegroundColor Red
    exit 1
}

function Run-Task($endpoint, $bodyObj, $outFile) {
    Write-Host "Dang gui task: $outFile ..." -ForegroundColor Cyan
    $jsonBody = $bodyObj | ConvertTo-Json -Depth 5
    
    $resp = Invoke-RestMethod -Uri "$Base$endpoint" -Method POST -Headers $headers -Body $jsonBody
    $taskId = $resp.task_id
    if (-not $taskId) { throw "Khong nhan duoc task_id tu G-Labs" }
    
    Write-Host "-> Task ID: $taskId. Dang cho xu ly..." -ForegroundColor Gray
    $elapsed = 0
    while ($elapsed -lt 300) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        $sj = Invoke-RestMethod -Uri "$Base/api/status/$taskId" -Method GET -Headers $headers
        Write-Host "Task $taskId : $($sj.status) ($($elapsed)s)"
        
        if ($sj.status -eq "completed") {
            $url = $sj.results[0]
            Invoke-WebRequest -Uri $url -Headers $headers -OutFile "$outDir\$outFile" -UseBasicParsing
            Write-Host "-> Thanh cong: $outDir\$outFile" -ForegroundColor Green
            return "$outDir\$outFile"
        }
        if ($sj.status -eq "failed") {
            throw "Task $taskId that bai: $($sj.error)"
        }
    }
    throw "Timeout khi cho task: $outFile"
}

# Test 1: Tạo ảnh Nano Banana
$imgBody = @{
    prompt = "a simple wooden cube on white background"
    model = "nano_banana_2"
    aspect_ratio = "16:9"
}
$imgFile = Run-Task "/api/image/generate" $imgBody "01_cube.jpg"
$imgBytes = [System.IO.File]::ReadAllBytes($imgFile)
$imgB64 = "data:image/jpeg;base64," + [Convert]::ToBase64String($imgBytes)

# Test 2: Mode text_to_video
$v1Body = @{
    prompt = "a golden retriever playing with a ball in park, no text overlay"
    mode = "text_to_video"
    resolution = @("720p")
    video_length = 6
}
Run-Task "/api/video/generate" $v1Body "02_text_to_video.mp4"

# Test 3: Mode start_image
$v2Body = @{
    prompt = "the wooden cube rotates slowly, no text overlay"
    mode = "start_image"
    reference_images = @($imgB64)
    resolution = @("720p")
    video_length = 6
}
Run-Task "/api/video/generate" $v2Body "03_start_image.mp4"

Write-Host "`n>>> KET QUA: PASS TEST M0.2 CO BAN <<<" -ForegroundColor Green
