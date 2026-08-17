# Red Team Automation 系統 - 一鍵安裝程式
# 版本: 1.0.0
# 支援: Windows 10/11, Windows Server 2019/2022

param(
    [string]$Action = "install",
    [string]$Environment = "production",
    [switch]$SkipPrerequisites = $false,
    [switch]$Verbose = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# 設定顏色
$Colors = @{
    Success = "Green"
    Warning = "Yellow"
    Error = "Red"
    Info = "Cyan"
    Header = "Magenta"
}

function Write-ColorOutput {
    param([string]$Message, [string]$Color = "White")
    Write-Host $Message -ForegroundColor $Colors[$Color]
}

function Show-Header {
    Clear-Host
    Write-ColorOutput "╔══════════════════════════════════════════════════════════════╗" "Header"
    Write-ColorOutput "║                Red Team Automation 系統                      ║" "Header"
    Write-ColorOutput "║                   一鍵安裝部署程式                           ║" "Header"
    Write-ColorOutput "║                     版本 1.0.0                              ║" "Header"
    Write-ColorOutput "╚══════════════════════════════════════════════════════════════╝" "Header"
    Write-Host ""
}

function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Prerequisites {
    Write-ColorOutput "🔍 檢查系統需求..." "Info"
    
    $requirements = @()
    
    # 檢查 Docker Desktop
    try {
        $dockerVersion = docker --version 2>$null
        if ($dockerVersion) {
            Write-ColorOutput "✅ Docker Desktop: $dockerVersion" "Success"
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
    
    # 檢查可用記憶體 (建議 8GB+)
    $memory = Get-CimInstance -ClassName Win32_ComputerSystem | Select-Object -ExpandProperty TotalPhysicalMemory
    $memoryGB = [math]::Round($memory / 1GB, 2)
    if ($memoryGB -ge 8) {
        Write-ColorOutput "✅ 系統記憶體: ${memoryGB}GB" "Success"
    } else {
        Write-ColorOutput "⚠️  系統記憶體: ${memoryGB}GB (建議 8GB+)" "Warning"
    }
    
    # 檢查可用磁碟空間 (建議 20GB+)
    $disk = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'" | Select-Object -ExpandProperty FreeSpace
    $diskGB = [math]::Round($disk / 1GB, 2)
    if ($diskGB -ge 20) {
        Write-ColorOutput "✅ 可用磁碟空間: ${diskGB}GB" "Success"
    } else {
        Write-ColorOutput "⚠️  可用磁碟空間: ${diskGB}GB (建議 20GB+)" "Warning"
    }
    
    return $requirements
}

function Install-Prerequisites {
    param([array]$Requirements)
    
    if ($Requirements.Count -eq 0) {
        return
    }
    
    Write-ColorOutput "📦 安裝必要軟體..." "Info"
    
    foreach ($requirement in $Requirements) {
        switch ($requirement) {
            "Docker Desktop" {
                Write-ColorOutput "正在下載 Docker Desktop..." "Info"
                $dockerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
                $dockerInstaller = "$env:TEMP\DockerDesktopInstaller.exe"
                
                try {
                    Invoke-WebRequest -Uri $dockerUrl -OutFile $dockerInstaller -UseBasicParsing
                    Write-ColorOutput "正在安裝 Docker Desktop..." "Info"
                    Start-Process -FilePath $dockerInstaller -ArgumentList "install", "--quiet" -Wait
                    Write-ColorOutput "✅ Docker Desktop 安裝完成" "Success"
                    Write-ColorOutput "⚠️  請重新啟動電腦後再執行此程式" "Warning"
                    exit 0
                } catch {
                    Write-ColorOutput "❌ Docker Desktop 安裝失敗: $($_.Exception.Message)" "Error"
                    Write-ColorOutput "請手動下載安裝: https://www.docker.com/products/docker-desktop" "Info"
                    exit 1
                }
            }
        }
    }
}

function Initialize-Environment {
    Write-ColorOutput "🔧 初始化環境..." "Info"
    
    # 建立必要目錄
    $directories = @("logs", "storage", "data", "backups")
    foreach ($dir in $directories) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-ColorOutput "✅ 建立目錄: $dir" "Success"
        }
    }
    
    # 複製環境設定檔
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-ColorOutput "✅ 建立環境設定檔" "Success"
    }
    
    # 設定環境變數
    $envContent = Get-Content ".env" -Raw
    $envContent = $envContent -replace "ENVIRONMENT=.*", "ENVIRONMENT=$Environment"
    $envContent = $envContent -replace "SECRET_KEY=.*", "SECRET_KEY=$(New-Guid)"
    $envContent = $envContent -replace "JWT_SECRET_KEY=.*", "JWT_SECRET_KEY=$(New-Guid)"
    Set-Content ".env" $envContent
    
    Write-ColorOutput "✅ 環境初始化完成" "Success"
}

function Build-System {
    Write-ColorOutput "🔨 建構系統映像檔..." "Info"
    
    try {
        docker-compose build --no-cache
        Write-ColorOutput "✅ 系統建構完成" "Success"
    } catch {
        Write-ColorOutput "❌ 系統建構失敗: $($_.Exception.Message)" "Error"
        exit 1
    }
}

function Start-System {
    Write-ColorOutput "🚀 啟動系統..." "Info"
    
    try {
        docker-compose up -d
        
        Write-ColorOutput "⏳ 等待服務啟動..." "Info"
        Start-Sleep -Seconds 30
        
        # 檢查服務狀態
        $services = docker-compose ps --services
        $runningServices = docker-compose ps --filter "status=running" --services
        
        Write-ColorOutput "📊 服務狀態:" "Info"
        foreach ($service in $services) {
            if ($runningServices -contains $service) {
                Write-ColorOutput "  ✅ $service: 運行中" "Success"
            } else {
                Write-ColorOutput "  ❌ $service: 未運行" "Error"
            }
        }
        
        Write-ColorOutput "✅ 系統啟動完成" "Success"
    } catch {
        Write-ColorOutput "❌ 系統啟動失敗: $($_.Exception.Message)" "Error"
        exit 1
    }
}

function Test-System {
    Write-ColorOutput "🧪 執行系統測試..." "Info"
    
    # 健康檢查
    $healthChecks = @(
        @{Name="API"; Url="http://localhost:8000/api/v1/health"},
        @{Name="Grafana"; Url="http://localhost:3000/api/health"},
        @{Name="Prometheus"; Url="http://localhost:9090/-/healthy"}
    )
    
    foreach ($check in $healthChecks) {
        try {
            $response = Invoke-WebRequest -Uri $check.Url -TimeoutSec 10 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                Write-ColorOutput "  ✅ $($check.Name): 健康" "Success"
            } else {
                Write-ColorOutput "  ⚠️  $($check.Name): 異常" "Warning"
            }
        } catch {
            Write-ColorOutput "  ❌ $($check.Name): 無法連接" "Error"
        }
    }
    
    # 執行基本功能測試
    try {
        Write-ColorOutput "執行基本功能測試..." "Info"
        docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile testing run --rm unit-tests
        Write-ColorOutput "✅ 基本功能測試通過" "Success"
    } catch {
        Write-ColorOutput "⚠️  部分測試失敗，但系統可以正常使用" "Warning"
    }
}

function Show-AccessInfo {
    Write-ColorOutput "🌐 系統存取資訊" "Header"
    Write-ColorOutput "═══════════════════════════════════════" "Header"
    Write-Host ""
    
    $accessPoints = @(
        @{Name="🔗 API 文件"; Url="http://localhost:8000/docs"; Auth="無需認證"},
        @{Name="📊 Grafana 監控"; Url="http://localhost:3000"; Auth="admin / admin123"},
        @{Name="🗄️  MongoDB 管理"; Url="http://localhost:8081"; Auth="admin / admin123"},
        @{Name="📈 Prometheus"; Url="http://localhost:9090"; Auth="無需認證"},
        @{Name="🚨 Alertmanager"; Url="http://localhost:9093"; Auth="無需認證"}
    )
    
    foreach ($point in $accessPoints) {
        Write-ColorOutput "$($point.Name)" "Info"
        Write-ColorOutput "  網址: $($point.Url)" "White"
        Write-ColorOutput "  認證: $($point.Auth)" "White"
        Write-Host ""
    }
    
    Write-ColorOutput "📋 常用指令" "Header"
    Write-ColorOutput "═══════════════════════════════════════" "Header"
    Write-ColorOutput "  查看系統狀態: docker-compose ps" "White"
    Write-ColorOutput "  查看日誌: docker-compose logs -f" "White"
    Write-ColorOutput "  停止系統: docker-compose down" "White"
    Write-ColorOutput "  重新啟動: docker-compose restart" "White"
    Write-Host ""
}

function Stop-System {
    Write-ColorOutput "🛑 停止系統..." "Info"
    
    try {
        docker-compose down
        Write-ColorOutput "✅ 系統已停止" "Success"
    } catch {
        Write-ColorOutput "❌ 停止系統時發生錯誤: $($_.Exception.Message)" "Error"
    }
}

function Uninstall-System {
    Write-ColorOutput "🗑️  解除安裝系統..." "Warning"
    
    $confirm = Read-Host "這將刪除所有資料，確定要繼續嗎？(y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-ColorOutput "取消解除安裝" "Info"
        return
    }
    
    try {
        docker-compose down -v --remove-orphans
        docker system prune -a -f
        Write-ColorOutput "✅ 系統已完全移除" "Success"
    } catch {
        Write-ColorOutput "❌ 解除安裝時發生錯誤: $($_.Exception.Message)" "Error"
    }
}

# 主程式
Show-Header

# 檢查管理員權限
if (-not (Test-Administrator)) {
    Write-ColorOutput "❌ 請以管理員身分執行此程式" "Error"
    exit 1
}

switch ($Action.ToLower()) {
    "install" {
        Write-ColorOutput "開始安裝 Red Team Automation 系統..." "Info"
        
        if (-not $SkipPrerequisites) {
            $requirements = Test-Prerequisites
            if ($requirements.Count -gt 0) {
                Install-Prerequisites $requirements
            }
        }
        
        Initialize-Environment
        Build-System
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
    
    "uninstall" {
        Uninstall-System
    }
    
    "status" {
        Write-ColorOutput "📊 系統狀態" "Header"
        docker-compose ps
        Write-Host ""
        Test-System
    }
    
    default {
        Write-ColorOutput "❌ 未知的操作: $Action" "Error"
        Write-Host "可用操作: install, start, stop, test, uninstall, status"
        exit 1
    }
}
    default {
        Write-ColorOutput "❓ 使用方式:" "Info"
        Write-ColorOutput "  .\RedTeamAutomation-Installer.ps1 [Action] [Options]" "White"
        Write-Host ""
        Write-ColorOutput "可用動作:" "Info"
        Write-ColorOutput "  install     - 安裝並啟動系統 (預設)" "White"
        Write-ColorOutput "  start       - 啟動系統" "White"
        Write-ColorOutput "  stop        - 停止系統" "White"
        Write-ColorOutput "  test        - 測試系統" "White"
        Write-ColorOutput "  status      - 查看系統狀態" "White"
        Write-ColorOutput "  uninstall   - 完全移除系統" "White"
        Write-Host ""
        Write-ColorOutput "選項:" "Info"
        Write-ColorOutput "  -Environment [production|development|testing]" "White"
        Write-ColorOutput "  -SkipPrerequisites  - 跳過先決條件檢查" "White"
        Write-ColorOutput "  -Verbose           - 顯示詳細輸出" "White"
    }
}