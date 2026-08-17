# Angelina AI Finance Agent

> A self-hosted, zero-cost AI-powered financial analysis agent with daily automated market insights and Telegram notifications.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-green.svg)](https://www.python.org/)
[![Podman](https://img.shields.io/badge/Container-Podman-purple.svg)](https://podman.io/)
[![RedHat](https://img.shields.io/badge/OS-Red%20Hat%20Linux-red.svg)](https://developers.redhat.com/)

---

## Overview

Angelina is a fully self-hosted AI financial analysis agent running on Red Hat Linux. It combines Gemini 2.5 Flash (free tier) with a RAG knowledge base to provide intelligent market analysis, daily automated reports, and interactive chat — all at **zero cost**.

**Key highlights:**

- **Gemini 2.5 Flash** (free tier) — AI-powered financial reasoning and analysis
- **ChromaDB + sentence-transformers** — RAG knowledge base for contextual retrieval
- **SQLite** — Persistent conversation memory with auto-summarization
- **FastAPI + Static Chat UI** — Lightweight web interface for interaction
- **Daily Automated Analysis** — Taiwan stock market, US markets, and financial news
- **Telegram Push Notifications** — Receive insights on your phone
- **Google Sheets Tracking** — Historical data logging and analysis records
- **Google Drive Knowledge Sync** — Centralized knowledge document management
- **Podman Containerized** — Rootless container deployment for security
- **Ansible Management** — Multi-VM orchestration and configuration
- **Red Hat Insights Monitoring** — System health and compliance tracking
- **100% Free** — Every component uses free tiers or open-source software

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Red Hat Linux Host                            │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Podman Container (Rootless)                 │  │
│  │                                                               │  │
│  │  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐    │  │
│  │  │  Chat UI    │───▶│   FastAPI    │───▶│  Gemini 2.5    │    │  │
│  │  │  (Static)   │    │   Backend    │    │  Flash (Free)  │    │  │
│  │  └─────────────┘    └──────┬───────┘    └────────────────┘    │  │
│  │                            │                                  │  │
│  │              ┌─────────────┼─────────────┐                    │  │
│  │              ▼             ▼             ▼                    │  │
│  │  ┌──────────────┐ ┌────────────┐ ┌──────────────┐            │  │
│  │  │   ChromaDB   │ │   SQLite   │ │  Scheduler   │            │  │
│  │  │  + Embeddings│ │   Memory   │ │ (APScheduler)│            │  │
│  │  └──────────────┘ └────────────┘ └──────┬───────┘            │  │
│  │                                          │                    │  │
│  └──────────────────────────────────────────┼────────────────────┘  │
│                                             │                       │
│  ┌──────────────────────────────────────────┴────────────────────┐  │
│  │              External Services           │                    │  │
│  │                                          ▼                    │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌──────────────┐            │  │
│  │  │ Telegram │  │ Google Sheets│  │ Google Drive │            │  │
│  │  │   Bot    │  │  (Tracking)  │  │  (Knowledge) │            │  │
│  │  └──────────┘  └──────────────┘  └──────────────┘            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌────────────────┐  ┌─────────────────┐                            │
│  │    Ansible     │  │  Red Hat        │                            │
│  │  (Management)  │  │  Insights       │                            │
│  └────────────────┘  └─────────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Features

### Interactive Chat
- **Web-based Chat UI** — Clean, responsive interface accessible via browser
- **`/learn` command** — Paste knowledge directly into the RAG knowledge base
- **`/fetch-url` command** — Scrape and ingest web pages into the knowledge base

### Automated Analysis
- **Daily market analysis** — Taiwan stock market (TAIEX, key sectors)
- **US market tracking** — S&P 500, NASDAQ, Dow Jones, key tech stocks
- **Financial news aggregation** — Curated news summaries and analysis
- **Scheduled execution** — Configurable cron-based daily runs

### Notifications & Tracking
- **Telegram push notifications** — Instant delivery of analysis results
- **Google Sheets historical tracking** — Append daily analysis for trend review
- **Google Drive knowledge sync** — Sync documents from Drive to knowledge base

### AI & Knowledge
- **RAG (Retrieval-Augmented Generation)** — Context-aware responses from your knowledge base
- **Conversation memory** — SQLite-backed with auto-summarization for long conversations
- **Model fallback** — `gemini-2.5-flash` to `gemini-flash-lite-latest` on failures
- **Auto-retry** — Graceful handling of API rate limits with exponential backoff

### Infrastructure
- **Podman containerized** — Rootless containers for enhanced security
- **Ansible multi-VM management** — Deploy and manage across multiple hosts
- **Automated weekly backups** — Data and knowledge base preservation
- **Red Hat Insights** — System monitoring and compliance

---

## Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| AI Model | Gemini 2.5 Flash (Free Tier) | Free |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Free |
| Vector DB | ChromaDB | Free |
| Database | SQLite | Free |
| Backend | FastAPI + Uvicorn | Free |
| Frontend | Static HTML/CSS/JS | Free |
| Scheduler | APScheduler | Free |
| Container | Podman (Rootless) | Free |
| OS | Red Hat Linux (Developer Subscription) | Free |
| Automation | Ansible | Free |
| Notifications | Telegram Bot API | Free |
| Tracking | Google Sheets API | Free |
| Knowledge Sync | Google Drive API | Free |
| Monitoring | Red Hat Insights | Free |

**Total cost: $0/month**

---

## Prerequisites

- **Red Hat Linux** — [Developer Subscription](https://developers.redhat.com/register) (free)
- **Python 3.12+**
- **Podman** (pre-installed on RHEL)
- **Gemini API Key** — Free from [Google AI Studio](https://aistudio.google.com/apikey)
- **Telegram Bot** (optional) — For push notifications, create via [@BotFather](https://t.me/BotFather)
- **Google Cloud Service Account** (optional) — For Sheets and Drive integration

---

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/angelina-finance-agent.git
cd angelina-finance-agent
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in your configuration (see [Configuration](#configuration) below).

### 3. Build the Container

```bash
podman build -t angelina-finance-agent .
```

### 4. Run the Container

```bash
podman run -d \
  --name angelina \
  --env-file .env \
  -p 8000:8000 \
  -v ./data:/app/data:Z \
  -v ./backups:/app/backups:Z \
  angelina-finance-agent
```

### 5. Access the Chat UI

Open your browser and navigate to:

```
http://YOUR_SERVER_IP:8000
```

### Alternative: Run Without Container

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Configuration

Create a `.env` file with the following variables:

```env
# === Required ===
GEMINI_API_KEY=YOUR_GEMINI_API_KEY

# === Application Settings ===
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

# === AI Model Settings ===
PRIMARY_MODEL=gemini-2.5-flash
FALLBACK_MODEL=gemini-flash-lite-latest
MAX_RETRIES=3
RETRY_DELAY=5

# === Knowledge Base ===
CHROMA_PERSIST_DIR=./data/chromadb
EMBEDDING_MODEL=all-MiniLM-L6-v2

# === Conversation Memory ===
SQLITE_DB_PATH=./data/conversations.db
SUMMARY_THRESHOLD=20

# === Telegram (Optional) ===
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID

# === Google Sheets (Optional) ===
GOOGLE_SHEETS_ID=YOUR_GOOGLE_SHEETS_ID
GOOGLE_SERVICE_ACCOUNT_FILE=./config/service-account.json

# === Google Drive (Optional) ===
GOOGLE_DRIVE_FOLDER_ID=YOUR_GOOGLE_DRIVE_FOLDER_ID

# === Scheduler ===
DAILY_ANALYSIS_HOUR=7
DAILY_ANALYSIS_MINUTE=30
DAILY_ANALYSIS_TIMEZONE=Asia/Taipei

# === Backup ===
BACKUP_DIR=./backups
BACKUP_RETENTION_DAYS=30
```

---

## Usage

### Chat Commands

| Command | Description | Example |
|---------|-------------|---------|
| (free text) | Ask any financial question | `What's your outlook on TSMC?` |
| `/learn` | Add knowledge to the RAG base | `/learn TSMC reported Q4 revenue of...` |
| `/fetch-url` | Scrape a URL into knowledge base | `/fetch-url https://example.com/article` |
| `/status` | Check system status | `/status` |
| `/clear` | Clear conversation history | `/clear` |

### Daily Automated Analysis

The agent runs daily analysis automatically based on your configured schedule (default: 7:30 AM Taipei time).

**Analysis includes:**
1. Taiwan stock market overview (TAIEX, sector performance)
2. US market summary (major indices, notable movers)
3. Financial news highlights
4. AI-generated insights and recommendations

Results are:
- Pushed to Telegram (if configured)
- Logged to Google Sheets (if configured)
- Stored in conversation history

### Manual Trigger

```bash
# Trigger daily analysis manually
curl -X POST http://localhost:8000/api/trigger-daily-analysis
```

---

## Management Commands

### Container Management

```bash
# Check status
podman ps -a --filter name=angelina

# View logs
podman logs -f angelina

# Restart
podman restart angelina

# Stop
podman stop angelina

# Remove and rebuild
podman rm angelina
podman build -t angelina-finance-agent .
```

### Backup & Restore

```bash
# Manual backup
./scripts/backup.sh

# Restore from backup
./scripts/restore.sh ./backups/backup-2024-01-15.tar.gz

# List backups
ls -la ./backups/
```

### Ansible Playbooks

```bash
# Deploy to remote host
ansible-playbook ansible/deploy.yml -i ansible/inventory.ini

# Update application
ansible-playbook ansible/update.yml -i ansible/inventory.ini

# Check status across all hosts
ansible-playbook ansible/status.yml -i ansible/inventory.ini

# Run backup on all hosts
ansible-playbook ansible/backup.yml -i ansible/inventory.ini
```

### Health Check

```bash
# API health endpoint
curl http://localhost:8000/api/health

# Knowledge base stats
curl http://localhost:8000/api/knowledge/stats

# Memory stats
curl http://localhost:8000/api/memory/stats
```

---

## Project Structure

```
angelina-finance-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   ├── routes.py           # API route definitions
│   │   └── websocket.py        # WebSocket chat handler
│   ├── core/
│   │   ├── config.py           # Configuration management
│   │   ├── gemini_client.py    # Gemini API client with fallback
│   │   └── scheduler.py        # APScheduler daily tasks
│   ├── knowledge/
│   │   ├── chromadb_store.py   # ChromaDB vector store
│   │   ├── embeddings.py       # Sentence-transformers embeddings
│   │   └── retriever.py        # RAG retrieval logic
│   ├── memory/
│   │   ├── sqlite_store.py     # SQLite conversation storage
│   │   └── summarizer.py       # Auto-summarization logic
│   ├── analysis/
│   │   ├── daily_runner.py     # Daily analysis orchestrator
│   │   ├── taiwan_market.py    # Taiwan stock market analysis
│   │   ├── us_market.py        # US market analysis
│   │   └── news_aggregator.py  # Financial news collection
│   ├── integrations/
│   │   ├── telegram.py         # Telegram bot notifications
│   │   ├── google_sheets.py    # Google Sheets logging
│   │   └── google_drive.py     # Google Drive sync
│   └── static/
│       ├── index.html          # Chat UI
│       ├── style.css           # UI styles
│       └── app.js              # Frontend logic
├── ansible/
│   ├── inventory.ini           # Host inventory
│   ├── deploy.yml              # Deployment playbook
│   ├── update.yml              # Update playbook
│   ├── backup.yml              # Backup playbook
│   └── status.yml              # Status check playbook
├── config/
│   └── service-account.json    # Google service account (gitignored)
├── data/
│   ├── chromadb/               # Vector database storage
│   └── conversations.db        # SQLite conversation database
├── backups/                    # Backup archives
├── scripts/
│   ├── backup.sh              # Backup script
│   └── restore.sh             # Restore script
├── tests/
│   ├── test_api.py
│   ├── test_knowledge.py
│   └── test_analysis.py
├── .env.example                # Environment template
├── .gitignore
├── Containerfile               # Podman/Docker build file
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT License
└── README.md                   # This file
```

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Please ensure your code:
- Passes existing tests
- Includes tests for new functionality
- Follows the existing code style
- Updates documentation as needed

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Google Gemini](https://ai.google.dev/) — AI model API (free tier)
- [ChromaDB](https://www.trychroma.com/) — Open-source vector database
- [sentence-transformers](https://www.sbert.net/) — Text embedding models
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Python web framework
- [Podman](https://podman.io/) — Rootless container engine
- [Red Hat Developer Program](https://developers.redhat.com/) — Free RHEL subscription

