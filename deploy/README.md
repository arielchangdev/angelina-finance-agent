# Red Team Automation 系統 - 部署指南

這是一個完整的紅隊自動化系統部署包，提供一鍵安裝和部署功能。

## 📋 系統需求

### 最低需求
- **記憶體**: 8GB RAM (建議 16GB+)
- **磁碟空間**: 20GB 可用空間 (建議 50GB+)
- **網路**: 穩定的網際網路連線

### 支援的作業系統
- **Windows**: Windows 10/11, Windows Server 2019/2022
- **Linux**: Ubuntu 20.04+, CentOS 8+, RHEL 8+
- **macOS**: macOS 10.15+

### 必要軟體
- Docker Desktop (Windows/macOS) 或 Docker Engine (Linux)
- Docker Compose

## 🚀 快速安裝

### Windows 用戶

1. **以管理員身分開啟 PowerShell**
2. **執行安裝程式**:
   ```powershell
   .\deploy\RedTeamAutomation-Installer.ps1
   ```

### Linux/macOS 用戶

1. **設定執行權限**:
   ```bash
   chmod +x deploy/RedTeamAutomation-Installer.sh
   ```

2. **執行安裝程式**:
   ```bash
   ./deploy/RedTeamAutomation-Installer.sh
   ```

## 📖 詳細安裝步驟

### 步驟 1: 下載部署包

```bash
# 如果你有 Git
git clone <repository-url>
cd red-team-automation

# 或者下載並解壓縮部署包
```

### 步驟 2: 執行安裝程式

**Windows**:
```powershell
# 完整安裝
.\deploy\RedTeamAutomation-Installer.ps1

# 指定環境
.\deploy\RedTeamAutomation-Installer.ps1 -Environment production

# 跳過先決條件檢查
.\deploy\RedTeamAutomation-Installer.ps1 -SkipPrerequisites
```

**Linux/macOS**:
```bash
# 完整安裝
./deploy/RedTeamAutomation-Installer.sh

# 指定環境
./deploy/RedTeamAutomation-Installer.sh install production

# 跳過先決條件檢查
./deploy/RedTeamAutomation-Installer.sh install production true
```

### 步驟 3: 等待安裝完成

安裝程式會自動執行以下步驟：

1. ✅ **檢查系統需求**
2. ✅ **安裝必要軟體** (Docker, Docker Compose)
3. ✅ **初始化環境**
4. ✅ **建構系統映像檔**
5. ✅ **啟動所有服務**
6. ✅ **執行系統測試**
7. ✅ **顯示存取資訊**

## 🌐 系統存取

安裝完成後，你可以透過以下網址存取系統：

| 服務 | 網址 | 帳號/密碼 | 說明 |
|------|------|-----------|------|
| **🔗 API 文件** | http://localhost:8000/docs | 無需認證 | Swagger API 文件 |
| **📊 Grafana 監控** | http://localhost:3000 | admin/admin123 | 系統監控儀表板 |
| **🗄️ MongoDB 管理** | http://localhost:8081 | admin/admin123 | 資料庫管理介面 |
| **📈 Prometheus** | http://localhost:9090 | 無需認證 | 指標收集系統 |
| **🚨 Alertmanager** | http://localhost:9093 | 無需認證 | 告警管理系統 |

## 🎯 使用指南

### 基本操作

1. **啟動系統**:
   ```bash
   # Windows
   .\deploy\RedTeamAutomation-Installer.ps1 -Action start
   
   # Linux/macOS
   ./deploy/RedTeamAutomation-Installer.sh start
   ```

2. **停止系統**:
   ```bash
   # Windows
   .\deploy\RedTeamAutomation-Installer.ps1 -Action stop
   
   # Linux/macOS
   ./deploy/RedTeamAutomation-Installer.sh stop
   ```

3. **查看系統狀態**:
   ```bash
   # Windows
   .\deploy\RedTeamAutomation-Installer.ps1 -Action status
   
   # Linux/macOS
   ./deploy/RedTeamAutomation-Installer.sh status
   ```

### 常用 Docker 指令

```bash
# 查看所有服務狀態
docker-compose ps

# 查看即時日誌
docker-compose logs -f

# 查看特定服務日誌
docker-compose logs -f redteam-api

# 重新啟動特定服務
docker-compose restart redteam-api

# 進入容器內部
docker-compose exec redteam-api bash
```

## 🧪 功能測試

### API 測試

1. **開啟 API 文件**: http://localhost:8000/docs
2. **測試健康檢查**: http://localhost:8000/api/v1/health
3. **執行基本 API 呼叫**

### 紅隊功能測試

1. **偵察模組**:
   - 被動偵察
   - 主動偵察
   - OSINT 收集

2. **漏洞掃描**:
   - 網路掃描
   - 服務掃描
   - 漏洞評估

3. **攻擊執行**:
   - 攻擊選擇
   - 權限提升
   - 攻擊執行

4. **報告生成**:
   - PDF 報告
   - 技術報告
   - 執行摘要

## 🔧 設定調整

### 環境變數設定

編輯 `.env` 檔案來調整系統設定：

```bash
# 應用程式設定
DEBUG=false
ENVIRONMENT=production
LOG_LEVEL=INFO

# 資料庫設定
MONGODB_URL=mongodb://mongodb:27017/redteam_automation
REDIS_URL=redis://redis:6379

# 安全設定
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret
```

### 連接埠設定

如果需要變更預設連接埠，編輯 `docker-compose.yml`：

```yaml
services:
  redteam-api:
    ports:
      - "8000:8000"  # 變更為其他連接埠
```

## 📊 監控和日誌

### Grafana 儀表板

1. 開啟 http://localhost:3000
2. 使用 admin/admin123 登入
3. 查看預設儀表板：
   - 系統監控
   - 應用程式效能
   - 紅隊活動概覽

### 日誌管理

```bash
# 查看所有服務日誌
docker-compose logs -f

# 查看特定時間範圍的日誌
docker-compose logs --since="1h" redteam-api

# 匯出日誌
docker-compose logs > system.log
```

## 🔒 安全考量

### 生產環境部署

1. **變更預設密碼**:
   ```bash
   # 編輯 .env 檔案
   MONGO_ROOT_PASSWORD=your-secure-password
   GRAFANA_ADMIN_PASSWORD=your-secure-password
   ```

2. **設定防火牆規則**:
   ```bash
   # 只允許必要的連接埠
   sudo ufw allow 8000/tcp  # API
   sudo ufw allow 3000/tcp  # Grafana (可選)
   ```

3. **啟用 HTTPS**:
   - 設定 SSL 憑證
   - 使用反向代理 (Nginx)

### 網路安全

- 確保系統部署在安全的網路環境中
- 定期更新系統和相依性
- 監控系統存取日誌

## 🛠️ 故障排除

### 常見問題

1. **Docker 服務無法啟動**:
   ```bash
   # 檢查 Docker 狀態
   docker info
   
   # 重新啟動 Docker
   sudo systemctl restart docker
   ```

2. **連接埠衝突**:
   ```bash
   # 檢查連接埠使用情況
   netstat -tulpn | grep :8000
   
   # 停止衝突的服務或變更連接埠
   ```

3. **記憶體不足**:
   ```bash
   # 檢查系統資源
   docker stats
   
   # 調整服務資源限制
   ```

### 日誌分析

```bash
# 檢查錯誤日誌
docker-compose logs | grep ERROR

# 檢查特定服務的問題
docker-compose logs redteam-api | tail -100
```

## 🔄 備份和恢復

### 資料備份

```bash
# 備份 MongoDB 資料
docker-compose exec mongodb mongodump --out /backup

# 備份整個系統
./scripts/backup_management.py create
```

### 系統恢復

```bash
# 恢復 MongoDB 資料
docker-compose exec mongodb mongorestore /backup

# 恢復整個系統
./scripts/backup_management.py restore
```

## 📞 支援和協助

如果遇到問題，請：

1. 檢查系統日誌
2. 查看故障排除指南
3. 確認系統需求
4. 聯繫技術支援

## 🎉 開始使用

安裝完成後，你可以：

1. 開啟 API 文件: http://localhost:8000/docs
2. 查看監控儀表板: http://localhost:3000
3. 開始執行紅隊測試
4. 生成測試報告

祝你使用愉快！🚀