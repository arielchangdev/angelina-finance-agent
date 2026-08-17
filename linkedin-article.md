# Angelina AI Finance Agent — LinkedIn 發佈文章

---

🤖 **如果一個 PM 能在週末自己打造一個 AI 財務分析師，你會怎麼想？**

---

這不是 Clickbait，這是我上個月真的做到的事。

身為一個 Project Manager，我每天管理的是需求、時程、利害關係人。但在 AI 時代，我問自己一個問題：

**「PM 只能管理專案，還是也能自己 Build？」**

答案是：當然可以。

---

## 💡 問題：我想要一個懂我的 AI 財務分析師

我對投資有自己的一套邏輯和筆記（存在 NotebookLM 裡），每天都會看台股和美股的走勢。但市面上的工具不是太貴，就是太通用——它們不認識我的投資風格，也不知道我關注哪些產業。

我想要的是：
- 每天自動分析台灣與美國股市
- 結合我自己的投資知識庫（不只是通用 AI 回答）
- 主動推送到我的手機
- 零成本運行

聽起來像是需要一整個工程團隊？其實不用。

---

## 🛠️ 解法：用免費工具打造企業級 AI Agent

我打造了 **Angelina AI Finance Agent**——一個完全自架、零成本的 AI 財務分析代理人。

技術堆疊：

| 元件 | 技術選擇 | 費用 |
|------|----------|------|
| AI 推理引擎 | Google Gemini 2.5 Flash（免費方案） | $0 |
| 作業系統 | Red Hat Enterprise Linux（Developer Subscription） | $0 |
| 向量資料庫 | ChromaDB（RAG 知識庫） | $0 |
| 容器化 | Podman（無 daemon、rootless） | $0 |
| API 框架 | FastAPI | $0 |
| 自動化管理 | Ansible（多 VM 管理） | $0 |
| **總成本** | | **$0/月** |

沒錯，每月零元。全部使用開源工具與免費方案。

---

## 🏗️ 架構設計思維

作為 PM，我在設計架構時不只想「能不能跑」，更在意「為什麼這樣設計」。

**為什麼選 Red Hat？**
Developer Subscription 免費，且有企業級穩定度。跑 24/7 的 Agent 需要的是可靠性，不是花俏。

**為什麼選 Podman 而非 Docker？**
Rootless、Daemonless，安全性更高。在個人 VM 上跑也更省資源。

**為什麼需要 RAG？**
通用 AI 只會給你通用答案。ChromaDB 讓我把自己的投資筆記向量化，Gemini 在分析時會參考「我的知識庫」，產出真正個人化的洞見。

**為什麼用 Ansible？**
一鍵部署、一鍵更新。PM 的思維就是：流程要可重複、可擴展。

整個系統跑在單一 VM 上，記憶體使用量不到 2GB。

---

## 📊 成果：每晚 11 點，AI 幫我做功課

現在每天晚上 11 點，我的 Telegram 會收到一則訊息。

📱 **Angelina 的每日分析報告包含：**
- 台股大盤走勢分析（TWSE 加權指數）
- 美股重點指標（S&P 500、NASDAQ）
- 當日重要財經新聞摘要
- 結合個人知識庫的投資觀察
- 關注個股的技術面分析

所有分析結果同步記錄到 Google Sheets，方便回顧歷史判斷的準確度。

系統還有 Auto-Learning 模組——每次互動都會更新 RAG 知識庫，讓分析越來越精準、越來越「懂我」。

---

## 🧠 心得：AI 時代的 PM 新定位

做完這個 Side Project，我有幾個深刻的體悟。

**1. PM 與工程師的界線正在模糊**

AI 工具大幅降低了建置門檻。會寫 Prompt、懂架構設計、能管理系統——這些 PM 本來就有的能力，現在可以直接轉化為可交付的產出。

**2. 開源 + 免費方案 = 個人也能擁有企業級架構**

Red Hat Developer Program 給你正式的 RHEL、Google 給你 Gemini 免費額度、ChromaDB 和 Podman 都是開源。這個組合讓個人開發者可以打造過去只有企業才負擔得起的系統。

**3. RAG 是通用 AI 到個人化智慧的橋樑**

沒有 RAG，AI 就只是一個比較聰明的搜尋引擎。有了 RAG，它變成了真正理解你、能參考你思維框架的顧問。

**4. 最好的學習方式就是 Build**

看再多文章、上再多課，都比不上自己動手做一個完整的系統。從架構設計到部署維運，每一步都是真實的學習。

---

## 🚀 開源分享

我把整個專案開源在 GitHub 上，包含完整的程式碼、部署文件、Ansible Playbook 以及詳細的 README：

👉 **https://github.com/arielchangdev/angelina-finance-agent**

歡迎 Fork、Star、或提 Issue 一起討論！

---

## 💬 想問大家一個問題

如果企業級工具都免費，**你會想打造什麼？**

也許是一個自動化客服、一個個人學習助理、或是一個專屬的內容創作引擎？

歡迎在留言區分享你的想法 👇

---

#AI #GenAI #Gemini #GoogleCloud #RedHat #OpenSource #FinTech #RAG #LLM #ProjectManagement #BuildInPublic #PersonalProject #TaiwanTech

---

## 🌐 English Brief

I built **Angelina AI Finance Agent** — a fully self-hosted, zero-cost AI financial analysis agent that delivers daily personalized market insights covering both Taiwan and US stock markets. The system runs on Red Hat Enterprise Linux using Podman containers, powered by Google Gemini 2.5 Flash (free tier), with ChromaDB handling a RAG knowledge base built from my own investment notes. Every night at 11 PM, I receive an automated analysis report via Telegram, with all data tracked historically in Google Sheets. The entire project is open source on GitHub — because in the AI era, Project Managers don't just manage. We build.

👉 GitHub: https://github.com/arielchangdev/angelina-finance-agent
