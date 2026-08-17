# Red Team Automation 系統打包腳本
# 建立可分發的部署包

param(
    [string]$Version = "1.0.0",
    [string]$OutputPath = "dist",
    [switch]$IncludeSource = $false
)

$ErrorActionPreference = "Stop"

Write-Host "Building Red Team Automation deployment package..." -ForegroundColor Green
Write-Host "Version: $Version" -ForegroundColor Cyan

# 建立輸出目錄
if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null

$packageName = "RedTeamAutomation-v$Version"
$packagePath = Join-Path $OutputPath $packageName

Write-Host "Creating package directory: $packagePath" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $packagePath -Force | Out-Null

# 複製必要檔案
$filesToCopy = @(
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.dev.yml",
    "docker-compose.test.yml",
    "Dockerfile",
    "Dockerfile.prod",
    "requirements.txt",
    ".env.example",
    ".dockerignore",
    "README.md",
    "README-TESTING.md"
)

Write-Host "Copying core files..." -ForegroundColor Cyan
foreach ($file in $filesToCopy) {
    if (Test-Path $file) {
        Copy-Item $file $packagePath -Force
        Write-Host "  ✅ $file" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  $file (不存在)" -ForegroundColor Yellow
    }
}

# 複製目錄
$directoriesToCopy = @(
    "deploy",
    "scripts",
    "docker",
    "templates"
)

if ($IncludeSource) {
    $directoriesToCopy += @("src", "tests", "frontend")
}

Write-Host "Copying directories..." -ForegroundColor Cyan
foreach ($dir in $directoriesToCopy) {
    if (Test-Path $dir) {
        Copy-Item $dir $packagePath -Recurse -Force
        Write-Host "  ✅ $dir" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  $dir (不存在)" -ForegroundColor Yellow
    }
}

# 建立啟動腳本
Write-Host "Creating startup scripts..." -ForegroundColor Cyan

$startScript = @"
@echo off
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                Red Team Automation 系統                      ║
echo ║                     快速啟動程式                             ║
echo ║                     版本 $Version                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

echo 正在啟動 Red Team Automation 系統...
echo.

REM 檢查 PowerShell 執行原則
powershell -Command "if ((Get-ExecutionPolicy) -eq 'Restricted') { Write-Host '設定 PowerShell 執行原則...' -ForegroundColor Yellow; Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force }"

REM 執行安裝程式
powershell -ExecutionPolicy Bypass -File "deploy\RedTeamAutomation-Installer.ps1"

pause
"@

Set-Content (Join-Path $packagePath "啟動系統.bat") $startScript -Encoding UTF8

# 建立 Linux/macOS 啟動腳本
$linuxStartScript = @"
#!/bin/bash
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                Red Team Automation 系統                      ║"
echo "║                     快速啟動程式                             ║"
echo "║                     版本 $Version                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo "正在啟動 Red Team Automation 系統..."
echo ""

# 設定執行權限
chmod +x deploy/RedTeamAutomation-Installer.sh

# 執行安裝程式
./deploy/RedTeamAutomation-Installer.sh

echo ""
echo "按任意鍵繼續..."
read -n 1
"@

Set-Content (Join-Path $packagePath "啟動系統.sh") $linuxStartScript -Encoding UTF8

# 建立版本資訊檔案
$versionInfo = @{
    version = $Version
    buildDate = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    components = @{
        api = "FastAPI 0.104.1"
        database = "MongoDB 7.0"
        cache = "Redis 7.2"
        monitoring = "Grafana 10.1.0 + Prometheus 2.47.0"
        frontend = "React 18.2.0"
    }
    requirements = @{
        memory = "8GB RAM (建議 16GB+)"
        disk = "20GB 可用空間 (建議 50GB+)"
        os = @("Windows 10/11", "Ubuntu 20.04+", "CentOS 8+", "macOS 10.15+")
    }
} | ConvertTo-Json -Depth 3

Set-Content (Join-Path $packagePath "version.json") $versionInfo -Encoding UTF8

# 建立快速指南
$quickGuide = @"
# Red Team Automation 系統 - 快速指南

## 🚀 快速啟動

### Windows 用戶
1. 雙擊 `啟動系統.bat`
2. 等待安裝完成
3. 開啟瀏覽器訪問 http://localhost:8000/docs

### Linux/macOS 用戶
1. 執行 `./啟動系統.sh`
2. 等待安裝完成
3. 開啟瀏覽器訪問 http://localhost:8000/docs

## 📋 系統需求
- 記憶體: 8GB RAM (建議 16GB+)
- 磁碟: 20GB 可用空間 (建議 50GB+)
- 網路: 穩定的網際網路連線

## 🌐 存取點
- API 文件: http://localhost:8000/docs
- 監控儀表板: http://localhost:3000 (admin/admin123)
- 資料庫管理: http://localhost:8081 (admin/admin123)

## 📞 需要協助？
請參閱 README.md 或 deploy/README.md 獲取詳細說明。

版本: $Version
建立日期: $((Get-Date).ToString("yyyy-MM-dd"))
"@

Set-Content (Join-Path $packagePath "快速指南.md") $quickGuide -Encoding UTF8

# 建立壓縮檔
Write-Host "Creating zip archive..." -ForegroundColor Cyan

$zipPath = Join-Path $OutputPath "$packageName.zip"
if (Get-Command Compress-Archive -ErrorAction SilentlyContinue) {
    Compress-Archive -Path $packagePath -DestinationPath $zipPath -Force
    Write-Host "✅ 壓縮檔已建立: $zipPath" -ForegroundColor Green
} else {
    Write-Host "⚠️  無法建立壓縮檔，請手動壓縮 $packagePath" -ForegroundColor Yellow
}

# 計算檔案大小
$packageSize = (Get-ChildItem $packagePath -Recurse | Measure-Object -Property Length -Sum).Sum
$packageSizeMB = [math]::Round($packageSize / 1MB, 2)

Write-Host ""
Write-Host "Deployment package created successfully!" -ForegroundColor Green
Write-Host "Location: $packagePath" -ForegroundColor Cyan
Write-Host "Size: $packageSizeMB MB" -ForegroundColor Cyan
Write-Host ""
Write-Host "Package contents:" -ForegroundColor Yellow
Write-Host "  - Core system files" -ForegroundColor White
Write-Host "  - Docker configurations" -ForegroundColor White
Write-Host "  - One-click installer" -ForegroundColor White
Write-Host "  - Quick start scripts" -ForegroundColor White
Write-Host "  - Complete documentation" -ForegroundColor White
if ($IncludeSource) {
    Write-Host "  - Source code" -ForegroundColor White
}
Write-Host ""
Write-Host "Ready to distribute to customers!" -ForegroundColor Green