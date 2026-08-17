# Red Team Automation 系統安裝程式 (最終版本)
param(
    [string]$Action = "install",
    [string]$Environment = "production",
    [switch]$SkipPrerequisites = $false,
    [switch]$Help = $false
)

if ($Help) {
    Write-Host @"
Red Team Automation 系統安裝程式

用法:
    .\RedTeamAutomation-Installer-Final.ps1 [參數]

參數:
    -Action <動作>          指定要執行的動作 (install, start, stop, test, status)
    -Environment <環境>     指定環境 (production, development)
    -SkipPrerequisites      跳過先決條件檢查
    -Help                   顯示此幫助資訊

範例:
    .\RedTeamAutomation-Installer-Final.ps1 -Action install
    .\RedTeamAutomation-Installer-Final.ps1 -Action start
    .\RedTeamAutomation-Installer-Final.ps1 -Action status
"@
    exit 0
}

$ErrorActionPreference = "Continue"

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    
    switch ($Color) {
        "Success" { Write-Host $Message -ForegroundColor Green }
        "Error" { Write-Host $Message -ForegroundColor Red }
        "Warning" { Write-Host $Message -ForegroundColor Yellow }
        "Info" { Write-Host $Message -ForegroundColor Cyan }
        "Header" { Write-Host $Message -ForegroundColor Magenta }
        default { Write-Host $Message -ForegroundColor White }
    }
}

function Show-Header {
    Write-Host ""
    Write-ColorOutput "╔══════════════════════════════════════════════════════════════╗" "Header"
    Write-ColorOutput "║                Red Team Automation 系統                      ║" "Header"
    Write-ColorOutput "║                     自動安裝程式                             ║" "Header"
    Write-ColorOutput "║                     版本 1.0.0                              ║" "Header"
    Write-ColorOutput "╚══════════════════════════════════════════════════════════════╝" "Header"
    Write-Host ""
}

function Test-Prerequisites {
    Write-ColorOutput "🔍 檢查系統需求..." "Info"
    $requirements = @()
    
    # 檢查 Docker
    try {
        $dockerVersion = docker --version 2>$null
        if ($dockerVersion) {
            Write-ColorOutput "✅ Docker: $dockerVersion" "Success"
        } else {
            $requirements += "Docker Desktop"
        }
    } catch {
        $requirements += "Docker Desktop"
    }
    
    # 檢查 Docker Compose
    try {
        $composeVersion = docker-compose --version 2>$null
        if ($composeVersion) {
            Write-ColorOutput "✅ Docker Compose: $composeVersion" "Success"
        } else {
            $requirements += "Docker Compose"
        }
    } catch {
        $requirements += "Docker Compose"
    }
    
    return $requirements
}

function Initialize-Environment {
    Write-ColorOutput "⚙️  初始化環境..." "Info"
    
    if ($Environment -eq "production" -and (Test-Path ".env.production")) {
        Copy-Item ".env.production" ".env" -Force
        Write-ColorOutput "✅ 使用生產環境配置" "Success"
    } elseif ($Environment -eq "development" -and (Test-Path ".env.development")) {
        Copy-Item ".env.development" ".env" -Force
        Write-ColorOutput "✅ 使用開發環境配置" "Success"
    } elseif (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env" -Force
        Write-ColorOutput "✅ 使用範例環境配置" "Success"
    }
    
    $directories = @("logs", "data", "backups")
    foreach ($dir in $directories) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-ColorOutput "✅ 創建目錄: $dir" "Success"
        }
    }
}

function Start-System {
    Write-ColorOutput "🚀 啟動系統..." "Info"
    
    try {
        docker-compose up -d
        Write-ColorOutput "⏳ 等待服務啟動..." "Info"
        Start-Sleep -Seconds 30
        Write-ColorOutput "✅ 系統啟動完成" "Success"
    } catch {
        Write-ColorOutput "❌ 系統啟動失敗: $($_.Exception.Message)" "Error"
        exit 1
    }
}

function Test-System {
    Write-ColorOutput "🧪 測試系統功能..." "Info"
    
    $healthChecks = @(
        @{ Name = "API 服務"; Url = "http://localhost:8000/health" },
        @{ Name = "Grafana"; Url = "http://localhost:3000/api/health" }
    )
    
    foreach ($check in $healthChecks) {
        try {
            $response = Invoke-WebRequest -Uri $check.Url -TimeoutSec 10 -UseBasicParsing -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                Write-ColorOutput "  ✅ $($check.Name): 正常" "Success"
            } else {
                Write-ColorOutput "  ⚠️  $($check.Name): 異常" "Warning"
            }
        } catch {
            Write-ColorOutput "  ❌ $($check.Name): 無法連接" "Error"
        }
    }
}

function Show-AccessInfo {
    Write-Host ""
    Write-ColorOutput "🌐 系統存取資訊" "Header"
    Write-ColorOutput "=" * 50 "Header"
    Write-ColorOutput "🔗 API 文件:      http://localhost:8000/docs" "Info"
    Write-ColorOutput "🎯 Web 介面:      http://localhost:8000" "Info"
    Write-ColorOutput "📊 Grafana 監控:  http://localhost:3000 (admin/admin123)" "Info"
    Write-ColorOutput "🗄️  MongoDB 管理:  http://localhost:8081 (admin/admin123)" "Info"
    Write-Host ""
    Write-ColorOutput "🎉 系統已準備就緒！請開啟瀏覽器訪問上述網址。" "Success"
    Write-Host ""
}

function Stop-System {
    Write-ColorOutput "🛑 停止系統..." "Info"
    try {
        docker-compose down
        Write-ColorOutput "✅ 系統已停止" "Success"
    } catch {
        Write-ColorOutput "❌ 停止系統失敗: $($_.Exception.Message)" "Error"
    }
}

# 主程式
Show-Header

switch ($Action.ToLower()) {
    "install" {
        Write-ColorOutput "開始安裝 Red Team Automation 系統..." "Info"
        
        if (-not $SkipPrerequisites) {
            $requirements = Test-Prerequisites
            if ($requirements.Count -gt 0) {
                Write-ColorOutput "❌ 缺少必要軟體: $($requirements -join ', ')" "Error"
                Write-ColorOutput "請先安裝 Docker Desktop: https://www.docker.com/products/docker-desktop" "Info"
                exit 1
            }
        }
        
        Initialize-Environment
        Start-System
        Test-System
        Show-AccessInfo
        
        Write-ColorOutput "🎉 安裝完成！系統已準備就緒。" "Success"
    }
    
    "start" {
        Start-System
        Show-AccessInfo
    }
    
    "stop" {
        Stop-System
    }
    
    "test" {
        Test-System
    }
    
    "status" {
        Write-ColorOutput "📊 系統狀態" "Header"
        docker-compose ps
        Write-Host ""
        Test-System
    }
    
    default {
        Write-ColorOutput "❌ 未知的操作: $Action" "Error"
        Write-Host "可用操作: install, start, stop, test, status"
        exit 1
    }
}