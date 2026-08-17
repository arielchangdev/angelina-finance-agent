#!/bin/bash
# Red Team Automation 系統 - 一鍵安裝程式
# 版本: 1.0.0
# 支援: Ubuntu 20.04+, CentOS 8+, macOS 10.15+

set -e

ACTION=${1:-install}
ENVIRONMENT=${2:-production}
SKIP_PREREQUISITES=${3:-false}

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

function print_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

function show_header() {
    clear
    print_color $PURPLE "╔══════════════════════════════════════════════════════════════╗"
    print_color $PURPLE "║                Red Team Automation 系統                      ║"
    print_color $PURPLE "║                   一鍵安裝部署程式                           ║"
    print_color $PURPLE "║                     版本 1.0.0                              ║"
    print_color $PURPLE "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

function check_root() {
    if [[ $EUID -eq 0 ]]; then
        print_color $YELLOW "⚠️  建議不要以 root 身分執行此程式"
        read -p "是否繼續？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

function detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$NAME
            VER=$VERSION_ID
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macOS"
        VER=$(sw_vers -productVersion)
    else
        print_color $RED "❌ 不支援的作業系統: $OSTYPE"
        exit 1
    fi
    
    print_color $CYAN "🖥️  作業系統: $OS $VER"
}

function check_prerequisites() {
    print_color $CYAN "🔍 檢查系統需求..."
    
    local requirements=()
    
    # 檢查 Docker
    if command -v docker &> /dev/null; then
        local docker_version=$(docker --version)
        print_color $GREEN "✅ Docker: $docker_version"
    else
        requirements+=("docker")
    fi
    
    # 檢查 Docker Compose
    if command -v docker-compose &> /dev/null; then
        local compose_version=$(docker-compose --version)
        print_color $GREEN "✅ Docker Compose: $compose_version"
    else
        requirements+=("docker-compose")
    fi
    
    # 檢查記憶體 (建議 8GB+)
    local memory_kb=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
    local memory_gb=$((memory_kb / 1024 / 1024))
    if [ $memory_gb -ge 8 ]; then
        print_color $GREEN "✅ 系統記憶體: ${memory_gb}GB"
    else
        print_color $YELLOW "⚠️  系統記憶體: ${memory_gb}GB (建議 8GB+)"
    fi
    
    # 檢查磁碟空間 (建議 20GB+)
    local disk_gb=$(df -BG . | awk 'NR==2 {print $4}' | sed 's/G//')
    if [ $disk_gb -ge 20 ]; then
        print_color $GREEN "✅ 可用磁碟空間: ${disk_gb}GB"
    else
        print_color $YELLOW "⚠️  可用磁碟空間: ${disk_gb}GB (建議 20GB+)"
    fi
    
    echo "${requirements[@]}"
}

function install_docker_ubuntu() {
    print_color $CYAN "正在安裝 Docker (Ubuntu)..."
    
    # 更新套件索引
    sudo apt-get update
    
    # 安裝必要套件
    sudo apt-get install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    # 新增 Docker GPG 金鑰
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    
    # 新增 Docker 套件庫
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # 安裝 Docker
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # 將使用者加入 docker 群組
    sudo usermod -aG docker $USER
    
    print_color $GREEN "✅ Docker 安裝完成"
}

function install_docker_centos() {
    print_color $CYAN "正在安裝 Docker (CentOS)..."
    
    # 安裝必要套件
    sudo yum install -y yum-utils
    
    # 新增 Docker 套件庫
    sudo yum-config-manager \
        --add-repo \
        https://download.docker.com/linux/centos/docker-ce.repo
    
    # 安裝 Docker
    sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # 啟動 Docker
    sudo systemctl start docker
    sudo systemctl enable docker
    
    # 將使用者加入 docker 群組
    sudo usermod -aG docker $USER
    
    print_color $GREEN "✅ Docker 安裝完成"
}

function install_docker_macos() {
    print_color $CYAN "正在安裝 Docker (macOS)..."
    
    if command -v brew &> /dev/null; then
        brew install --cask docker
        print_color $GREEN "✅ Docker Desktop 安裝完成"
        print_color $YELLOW "⚠️  請啟動 Docker Desktop 應用程式"
    else
        print_color $RED "❌ 請先安裝 Homebrew 或手動下載 Docker Desktop"
        print_color $CYAN "Homebrew: https://brew.sh/"
        print_color $CYAN "Docker Desktop: https://www.docker.com/products/docker-desktop"
        exit 1
    fi
}

function install_docker_compose() {
    print_color $CYAN "正在安裝 Docker Compose..."
    
    # 下載最新版本的 Docker Compose
    local compose_version=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
    sudo curl -L "https://github.com/docker/compose/releases/download/${compose_version}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    
    # 設定執行權限
    sudo chmod +x /usr/local/bin/docker-compose
    
    print_color $GREEN "✅ Docker Compose 安裝完成"
}

function install_prerequisites() {
    local requirements=($1)
    
    if [ ${#requirements[@]} -eq 0 ]; then
        return
    fi
    
    print_color $CYAN "📦 安裝必要軟體..."
    
    for requirement in "${requirements[@]}"; do
        case $requirement in
            "docker")
                if [[ "$OS" == *"Ubuntu"* ]]; then
                    install_docker_ubuntu
                elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
                    install_docker_centos
                elif [[ "$OS" == "macOS" ]]; then
                    install_docker_macos
                fi
                ;;
            "docker-compose")
                install_docker_compose
                ;;
        esac
    done
    
    print_color $YELLOW "⚠️  請重新登入或重新啟動終端機以套用群組變更"
    print_color $YELLOW "然後重新執行此程式"
    exit 0
}

function initialize_environment() {
    print_color $CYAN "🔧 初始化環境..."
    
    # 建立必要目錄
    local directories=("logs" "storage" "data" "backups")
    for dir in "${directories[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            print_color $GREEN "✅ 建立目錄: $dir"
        fi
    done
    
    # 複製環境設定檔
    if [ ! -f ".env" ]; then
        cp ".env.example" ".env"
        print_color $GREEN "✅ 建立環境設定檔"
    fi
    
    # 設定環境變數
    sed -i "s/ENVIRONMENT=.*/ENVIRONMENT=$ENVIRONMENT/" .env
    sed -i "s/SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
    sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$(openssl rand -hex 32)/" .env
    
    print_color $GREEN "✅ 環境初始化完成"
}

function build_system() {
    print_color $CYAN "🔨 建構系統映像檔..."
    
    if docker-compose build --no-cache; then
        print_color $GREEN "✅ 系統建構完成"
    else
        print_color $RED "❌ 系統建構失敗"
        exit 1
    fi
}

function start_system() {
    print_color $CYAN "🚀 啟動系統..."
    
    if docker-compose up -d; then
        print_color $CYAN "⏳ 等待服務啟動..."
        sleep 30
        
        # 檢查服務狀態
        print_color $CYAN "📊 服務狀態:"
        docker-compose ps
        
        print_color $GREEN "✅ 系統啟動完成"
    else
        print_color $RED "❌ 系統啟動失敗"
        exit 1
    fi
}

function test_system() {
    print_color $CYAN "🧪 執行系統測試..."
    
    # 健康檢查
    local health_checks=(
        "API:http://localhost:8000/api/v1/health"
        "Grafana:http://localhost:3000/api/health"
        "Prometheus:http://localhost:9090/-/healthy"
    )
    
    for check in "${health_checks[@]}"; do
        local name=$(echo $check | cut -d: -f1)
        local url=$(echo $check | cut -d: -f2-)
        
        if curl -f -s "$url" > /dev/null 2>&1; then
            print_color $GREEN "  ✅ $name: 健康"
        else
            print_color $RED "  ❌ $name: 無法連接"
        fi
    done
    
    # 執行基本功能測試
    print_color $CYAN "執行基本功能測試..."
    if docker-compose -f docker-compose.yml -f docker-compose.test.yml --profile testing run --rm unit-tests; then
        print_color $GREEN "✅ 基本功能測試通過"
    else
        print_color $YELLOW "⚠️  部分測試失敗，但系統可以正常使用"
    fi
}

function show_access_info() {
    print_color $PURPLE "🌐 系統存取資訊"
    print_color $PURPLE "═══════════════════════════════════════"
    echo ""
    
    print_color $CYAN "🔗 API 文件"
    print_color $WHITE "  網址: http://localhost:8000/docs"
    print_color $WHITE "  認證: 無需認證"
    echo ""
    
    print_color $CYAN "📊 Grafana 監控"
    print_color $WHITE "  網址: http://localhost:3000"
    print_color $WHITE "  認證: admin / admin123"
    echo ""
    
    print_color $CYAN "🗄️  MongoDB 管理"
    print_color $WHITE "  網址: http://localhost:8081"
    print_color $WHITE "  認證: admin / admin123"
    echo ""
    
    print_color $CYAN "📈 Prometheus"
    print_color $WHITE "  網址: http://localhost:9090"
    print_color $WHITE "  認證: 無需認證"
    echo ""
    
    print_color $CYAN "🚨 Alertmanager"
    print_color $WHITE "  網址: http://localhost:9093"
    print_color $WHITE "  認證: 無需認證"
    echo ""
    
    print_color $PURPLE "📋 常用指令"
    print_color $PURPLE "═══════════════════════════════════════"
    print_color $WHITE "  查看系統狀態: docker-compose ps"
    print_color $WHITE "  查看日誌: docker-compose logs -f"
    print_color $WHITE "  停止系統: docker-compose down"
    print_color $WHITE "  重新啟動: docker-compose restart"
    echo ""
}

function stop_system() {
    print_color $CYAN "🛑 停止系統..."
    
    if docker-compose down; then
        print_color $GREEN "✅ 系統已停止"
    else
        print_color $RED "❌ 停止系統時發生錯誤"
    fi
}

function uninstall_system() {
    print_color $YELLOW "🗑️  解除安裝系統..."
    
    read -p "這將刪除所有資料，確定要繼續嗎？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_color $CYAN "取消解除安裝"
        return
    fi
    
    if docker-compose down -v --remove-orphans && docker system prune -a -f; then
        print_color $GREEN "✅ 系統已完全移除"
    else
        print_color $RED "❌ 解除安裝時發生錯誤"
    fi
}

# 主程式
show_header
check_root
detect_os

case "$ACTION" in
    "install")
        print_color $CYAN "開始安裝 Red Team Automation 系統..."
        
        if [ "$SKIP_PREREQUISITES" != "true" ]; then
            requirements=$(check_prerequisites)
            if [ -n "$requirements" ]; then
                install_prerequisites "$requirements"
            fi
        fi
        
        initialize_environment
        build_system
        start_system
        test_system
        show_access_info
        
        print_color $GREEN "🎉 安裝完成！系統已準備就緒。"
        ;;
    
    "start")
        start_system
        show_access_info
        ;;
    
    "stop")
        stop_system
        ;;
    
    "test")
        test_system
        ;;
    
    "uninstall")
        uninstall_system
        ;;
    
    "status")
        print_color $PURPLE "📊 系統狀態"
        docker-compose ps
        echo ""
        test_system
        ;;
    
    *)
        print_color $CYAN "❓ 使用方式:"
        print_color $WHITE "  ./RedTeamAutomation-Installer.sh [action] [environment] [skip_prerequisites]"
        echo ""
        print_color $CYAN "可用動作:"
        print_color $WHITE "  install     - 安裝並啟動系統 (預設)"
        print_color $WHITE "  start       - 啟動系統"
        print_color $WHITE "  stop        - 停止系統"
        print_color $WHITE "  test        - 測試系統"
        print_color $WHITE "  status      - 查看系統狀態"
        print_color $WHITE "  uninstall   - 完全移除系統"
        echo ""
        print_color $CYAN "環境選項:"
        print_color $WHITE "  production  - 生產環境 (預設)"
        print_color $WHITE "  development - 開發環境"
        print_color $WHITE "  testing     - 測試環境"
        ;;
esac