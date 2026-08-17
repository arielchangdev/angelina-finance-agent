"""
Daily Stock Market Analysis Script
Runs on RedHat VM, fetches Taiwan and US market data,
generates AI-powered analysis, and sends reports via Telegram.
"""

import sys
sys.path.insert(0, '/opt/angelina')

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

# Google Sheets tracking
try:
    from app.sheets_tracker import record_daily_data
    SHEETS_ENABLED = True
except ImportError:
    SHEETS_ENABLED = False
    print("[WARN] sheets_tracker not available")

# Configuration
TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
TELEGRAM_CHAT_ID = 'YOUR_TELEGRAM_CHAT_ID'
GEMINI_API_KEY = 'YOUR_GEMINI_API_KEY'
ANGELINA_URL = 'http://localhost:8080'
TW_TZ = timezone(timedelta(hours=8))
GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-flash-lite-latest']

# Track sent messages to avoid duplicates
SENT_HASHES_FILE = '/tmp/daily_analysis_sent_hashes.json'


def load_sent_hashes():
    """Load previously sent message hashes."""
    try:
        with open(SENT_HASHES_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_sent_hash(msg_hash):
    """Save a message hash to prevent duplicate sends."""
    hashes = load_sent_hashes()
    hashes.add(msg_hash)
    # Keep only last 100 hashes
    hashes_list = list(hashes)[-100:]
    with open(SENT_HASHES_FILE, 'w') as f:
        json.dump(hashes_list, f)


def get_message_hash(text):
    """Generate a hash for message deduplication."""
    today = datetime.now(TW_TZ).strftime('%Y-%m-%d')
    return hashlib.md5(f"{today}:{text.replace('\n', ' ')[:500]}".encode()).hexdigest()


async def fetch_twse_daily(client):
    """Fetch Taiwan stock market data from TWSE API."""
    today = datetime.now(TW_TZ)
    date_str = today.strftime('%Y%m%d')
    results = {}

    # Monthly summary (FMTQIK) - get last row for today's data
    try:
        url = f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={date_str}"
        resp = await client.get(url, timeout=30)
        data = resp.json()
        if data.get('stat') == 'OK' and data.get('data'):
            last_row = data['data'][-1]
            fields = data.get('fields', [])
            results['monthly_summary'] = dict(zip(fields, last_row))
        else:
            results['monthly_summary'] = None
    except Exception as e:
        print(f"  [WARN] Failed to fetch FMTQIK: {e}")
        results['monthly_summary'] = None

    # Top gainers (MI_INDEX20)
    try:
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX20?response=json&date={date_str}"
        resp = await client.get(url, timeout=30)
        data = resp.json()
        if data.get('stat') == 'OK' and data.get('data'):
            fields = data.get('fields', [])
            results['top_gainers'] = [dict(zip(fields, row)) for row in data['data'][:10]]
        else:
            results['top_gainers'] = []
    except Exception as e:
        print(f"  [WARN] Failed to fetch MI_INDEX20: {e}")
        results['top_gainers'] = []

    # Institutional investors (BFI82U)
    try:
        url = f"https://www.twse.com.tw/fund/BFI82U?response=json&dayDate={date_str}&type=day"
        resp = await client.get(url, timeout=30)
        data = resp.json()
        if data.get('stat') == 'OK' and data.get('data'):
            fields = data.get('fields', [])
            results['institutional'] = [dict(zip(fields, row)) for row in data['data']]
        else:
            results['institutional'] = []
    except Exception as e:
        print(f"  [WARN] Failed to fetch BFI82U: {e}")
        results['institutional'] = []

    return results

async def fetch_us_market(client):
    """Fetch US market data from Yahoo Finance."""
    symbols = {'^GSPC': 'S&P 500', '^IXIC': 'NASDAQ', '^DJI': 'Dow Jones'}
    results = {}

    for symbol, name in symbols.items():
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                f"?range=5d&interval=1d"
            )
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = await client.get(url, headers=headers, timeout=30)
            data = resp.json()

            chart = data.get('chart', {}).get('result', [{}])[0]
            meta = chart.get('meta', {})
            indicators = chart.get('indicators', {}).get('quote', [{}])[0]
            closes = indicators.get('close', [])

            if closes and len(closes) >= 2:
                latest = closes[-1]
                prev = closes[-2]
                if latest and prev:
                    change = latest - prev
                    change_pct = (change / prev) * 100
                    results[name] = {
                        'price': round(latest, 2),
                        'change': round(change, 2),
                        'change_pct': round(change_pct, 2),
                        'currency': meta.get('currency', 'USD')
                    }
                else:
                    results[name] = None
            else:
                results[name] = None
        except Exception as e:
            print(f"  [WARN] Failed to fetch {name}: {e}")
            results[name] = None

    return results


async def fetch_news(client):
    """Scrape news headlines from Yahoo Taiwan stock news."""
    headlines = []
    try:
        url = "https://tw.stock.yahoo.com/news/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        resp = await client.get(url, headers=headers, timeout=30)
        html = resp.text

        # Look for news article titles in the HTML
        pattern = r'<h3[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</h3>'
        matches = re.findall(pattern, html, re.DOTALL)
        if matches:
            headlines = [m.strip() for m in matches[:10] if m.strip()]

        # Fallback: try another pattern
        if not headlines:
            pattern = r'class="[^"]*Fz\(16px\)[^"]*"[^>]*>([^<]+)<'
            matches = re.findall(pattern, html)
            headlines = [m.strip() for m in matches[:10] if m.strip()]

        # Another fallback pattern
        if not headlines:
            pattern = r'<a[^>]*href="/news/[^"]*"[^>]*title="([^"]*)"'
            matches = re.findall(pattern, html)
            headlines = [m.strip() for m in matches[:10] if m.strip()]

    except Exception as e:
        print(f"  [WARN] Failed to fetch news: {e}")

    return headlines


async def get_knowledge_context():
    """Query Angelina knowledge base for investment strategy context."""
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "message": "/learning-stats",
                "session_id": "daily_analysis",
                "language": "zh-TW"
            }
            for attempt in range(2):
                resp = await client.post(
                    f"{ANGELINA_URL}/chat",
                    json=payload,
                    timeout=60
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get('reply', '')
                elif resp.status_code in (502, 503, 429):
                    print(f"  [RETRY] KB returned {resp.status_code}, waiting 15s")
                    import asyncio as _aio3
                    await _aio3.sleep(15)
                else:
                    break
            print(f"  [WARN] Knowledge base returned status {resp.status_code}")
            return ""
    except Exception as e:
        print(f"  [WARN] Failed to query knowledge base: {e}")
        return ""

async def generate_report(market_data, knowledge, is_weekend=False):
    """Generate analysis report using Gemini AI with 3-stage pipeline.

    Stage 1: Analyze raw market data -> structured market assessment (JSON)
    Stage 2: Search knowledge base with Stage 1 results (local ChromaDB, no API)
    Stage 3: Generate final report with all context + mandatory direction constraint
    """
    tw_data = market_data.get('taiwan', {})
    us_data = market_data.get('us', {})
    news = market_data.get('news', [])

    # Build market data summary for the prompt
    tw_summary_parts = []
    if tw_data.get('monthly_summary'):
        tw_summary_parts.append(
            f"月成交資訊: {json.dumps(tw_data['monthly_summary'], ensure_ascii=False)}"
        )
    if tw_data.get('top_gainers'):
        gainers_str = json.dumps(tw_data['top_gainers'][:5], ensure_ascii=False)
        tw_summary_parts.append(f"漲幅前五: {gainers_str}")
    if tw_data.get('institutional'):
        inst_str = json.dumps(tw_data['institutional'], ensure_ascii=False)
        tw_summary_parts.append(f"三大法人: {inst_str}")

    # PRE-PROCESS: Format large numbers in market data BEFORE sending to Gemini
    import re as _re
    def _fmt(val):
        """Convert raw number strings to readable format."""
        if not isinstance(val, str):
            return val
        clean = val.replace(',', '').strip()
        try:
            num = float(clean)
            if num >= 1_000_000_000_000:
                return f"約 {num/1_000_000_000_000:.2f} 兆元"
            elif num >= 100_000_000:
                return f"約 {num/100_000_000:.1f} 億元"
        except (ValueError, TypeError):
            pass
        return val

    tw_summary_parts = [_re.sub(r'[\d,]{9,}', lambda m: _fmt(m.group(0)), p) for p in tw_summary_parts]

    tw_section = "\n".join(tw_summary_parts) if tw_summary_parts else "今日無台股資料"

    us_parts = []
    for name, info in us_data.items():
        if info:
            us_parts.append(
                f"{name}: {info['price']} ({info['change']:+.2f}, {info['change_pct']:+.2f}%)"
            )
    us_section = "\n".join(us_parts) if us_parts else "今日無美股資料"

    news_section = "\n".join(f"- {h}" for h in news) if news else "今日無重要新聞"

    knowledge_section = knowledge if knowledge else "無知識庫context"

    today_str = datetime.now(TW_TZ).strftime('%Y年%m月%d日')

    # --- Reusable Gemini API call helper ---
    async def _call_gemini(client, prompt_text, temperature=0.7, max_tokens=4096):
        """Call Gemini API with model fallback and retry logic. Returns text or None."""
        for model_name in GEMINI_MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={GEMINI_API_KEY}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
            }
            resp = None
            for attempt in range(3):
                resp = await client.post(url, json=payload, timeout=120)
                if resp.status_code == 200:
                    break
                elif resp.status_code in (503, 429):
                    wait = 20 * (attempt + 1)
                    print(f"  [RETRY] {model_name} returned {resp.status_code}, waiting {wait}s ({attempt+1}/3)")
                    await asyncio.sleep(wait)
                else:
                    break

            if resp and resp.status_code == 200:
                print(f"  [OK] Model {model_name} succeeded")
                data = resp.json()
                candidates = data.get('candidates', [])
                if candidates:
                    content_parts = candidates[0].get('content', {}).get('parts', [])
                    if content_parts:
                        full_text = ""
                        for p in content_parts:
                            if 'text' in p:
                                full_text += p['text']
                        return full_text
            else:
                print(f"  [WARN] Model {model_name} failed: HTTP {resp.status_code if resp else 'no response'} - {resp.text[:500] if resp else ''}")
                continue
        return None

    # --- Weekend mode: skip Stage 1/2, go directly to Stage 3 ---
    if is_weekend:
        weekend_prompt = (
            "❗ 今天是週末，台股休市。\n"
            "報告標題必須為《台股週報與下週展望》。\n"
            "內容架構：上週盤態總結 -> 美股與全球宏觀 -> 下週觀盤重點 -> 操作建議。\n"
            "嚴禁出現「今日無交易數據」或模擬當日盤態。\n\n"
            "# Role & Tone\n"
            "你是一位專業、客觀且具備實戰經驗的台灣股市首席分析師。報告應兼具數據精準度、高可讀性與實用操作指引。\n\n"
            "# Core Execution Rules\n"
            "1. 報告長度：總輸出字數嚴格控制在 800-1000 字。說話直奔主題、精簡贅字，確保完整產出到操作建議與免責聲明。\n"
            "2. 盤態與中長期語氣調和：當日大漲時先肯定多方動能，再以「逢高順勢調節/注意高檔風險」帶出中長期警示。嚴禁在大漲日宣告市場極度悲觀。\n"
            "3. 數據格式化：金額大於億一律四捨五入換算為億元或兆元（保留小數點後1-2位）。絕對禁止輸出原始多位數數字。\n"
            "4. 防幻覺：指數點位與前一交易日維持連續性，絕對禁止捏造偏離現況超過10%的數字。\n"
            "5. 隱藏系統語言：絕對禁止提及「知識庫」「投資框架」「新聞列表為選單」「無具體新聞」等。新聞不足時直接以「從量價結構與籌碼動向觀察」帶過。\n"
            "6. 技術面白話化：MA5=5日均線/極短線成本, MA20=20日均線/月線。\n"
            "7. 報告末尾必須包含：倉位控制建議與具體停損/觀察點位。\n\n"
            f"# 市場數據\n{tw_section}\n\n{us_section}\n\n{news_section}\n\n"
            f"# 投資知識參考\n{knowledge_section}\n\n"
            "# 輸出格式\n"
            "請依序產出：1.上週回顧 2.美股狀況 3.下週展望 4.操作建議(含倉位與停損位) 5.免責聲明\n"
            "❗ 總字數不得超過1000字。必須完整產出到免責聲明。"
        )
        try:
            async with httpx.AsyncClient() as client:
                result = await _call_gemini(client, weekend_prompt, temperature=0.7, max_tokens=8192)
                return result
        except Exception as e:
            print(f"  [ERROR] Failed to generate weekend report: {e}")
            return None

    # ========== STAGE 1: Structured Market Assessment ==========
    print("  [Stage 1] Analyzing market data for structured assessment...")
    stage1_assessment = None
    try:
        stage1_prompt = (
            "You are a market data analyst. Analyze the following raw market data and produce a SHORT "
            "structured assessment in JSON format. Do NOT add any opinion or investment advice.\n\n"
            f"## Taiwan Market Data\n{tw_section}\n\n"
            f"## US Market Data\n{us_section}\n\n"
            "## Output (JSON only, no markdown fences):\n"
            "{\n"
            '  "market_direction": "bullish" or "bearish" or "neutral",\n'
            '  "tw_change_pct": <the percentage change as a number>,\n'
            '  "key_events": ["observation 1", "observation 2", "observation 3"],\n'
            '  "institutional_flow": "<net buy/sell summary in one sentence>"\n'
            "}\n\n"
            "Rules:\n"
            "- bullish: index up > +0.5%\n"
            "- bearish: index down < -0.5%\n"
            "- neutral: between -0.5% and +0.5%\n"
            "- Only use the data provided. Do NOT hallucinate numbers.\n"
            "- Output ONLY the JSON object, nothing else."
        )

        async with httpx.AsyncClient() as client:
            stage1_text = await _call_gemini(client, stage1_prompt, temperature=0.2, max_tokens=1024)

        if stage1_text:
            print(f"  [Stage 1] Raw response: {repr(stage1_text[:300])}")
            print(f"  [Stage 1] Raw response: {repr(stage1_text[:300])}")
            # Parse the JSON from Stage 1 response
            # Robust JSON extraction - find the JSON object anywhere in response
            text = stage1_text.strip()
            # Remove markdown code fences
            if "```" in text:
                import re as _re2
                json_match = _re2.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
                if json_match:
                    text = json_match.group(0)
                else:
                    text = text.replace("```json", "").replace("```", "").strip()
            # Find the JSON object
            start_idx = text.find("{")
            end_idx = text.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                text = text[start_idx:end_idx]
            stage1_assessment = json.loads(text)
            print(f"  [Stage 1] Assessment: direction={stage1_assessment.get('market_direction')}, "
                  f"change={stage1_assessment.get('tw_change_pct')}%")
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [Stage 1] JSON parse failed: {e}. Trying regex extraction...")
        # Regex fallback: extract key fields from the text
        try:
            import re as _re3
            direction_match = _re3.search(r'"market_direction"\s*:\s*"(bullish|bearish|neutral)"', stage1_text)
            pct_match = _re3.search(r'"tw_change_pct"\s*:\s*([\d.\-+]+)', stage1_text)
            if direction_match:
                stage1_assessment = {
                    "market_direction": direction_match.group(1),
                    "tw_change_pct": float(pct_match.group(1)) if pct_match else 0.0,
                    "key_events": [],
                    "institutional_flow": ""
                }
                print(f"  [Stage 1] Regex extraction: direction={stage1_assessment['market_direction']}, pct={stage1_assessment['tw_change_pct']}")
            else:
                print(f"  [Stage 1] Regex extraction also failed. Falling back.")
                stage1_assessment = None
        except Exception:
            stage1_assessment = None

    # If Stage 1 failed, fall back to original single-stage behavior
    if stage1_assessment is None:
        print("  [FALLBACK] Using single-stage generation (Stage 1 failed)...")
        fallback_prompt = (
            "# Role & Tone\n"
            "你是一位專業、客觀且具備實戰經驗的台灣股市首席分析師。報告應兼具數據精準度、高可讀性與實用操作指引。\n\n"
            "# Core Execution Rules\n"
            "1. 報告長度：總輸出字數嚴格控制在 800-1000 字。說話直奔主題、精簡贅字，確保完整產出到操作建議與免責聲明。\n"
            "2. 盤態與中長期語氣調和：當日大漲時先肯定多方動能，再以「逢高順勢調節/注意高檔風險」帶出中長期警示。嚴禁在大漲日宣告市場極度悲觀。\n"
            "3. 數據格式化：金額大於億一律四捨五入換算為億元或兆元（保留小數點後1-2位）。絕對禁止輸出原始多位數數字。\n"
            "4. 防幻覺：指數點位與前一交易日維持連續性，絕對禁止捏造偏離現況超過10%的數字。\n"
            "5. 隱藏系統語言：絕對禁止提及「知識庫」「投資框架」「新聞列表為選單」「無具體新聞」等。新聞不足時直接以「從量價結構與籌碼動向觀察」帶過。\n"
            "6. 技術面白話化：MA5=5日均線/極短線成本, MA20=20日均線/月線。\n"
            "7. 報告末尾必須包含：倉位控制建議與具體停損/觀察點位。\n\n"
            f"# 市場數據\n{tw_section}\n\n{us_section}\n\n{news_section}\n\n"
            f"# 投資知識參考\n{knowledge_section}\n\n"
            "# 輸出格式\n"
            "請依序產出：1.台股摘要 2.美股狀況 3.趨勢分析 4.操作建議(含倉位與停損位) 5.免責聲明\n"
            "❗ 總字數不得超過1000字。必須完整產出到免責聲明。"
        )
        try:
            async with httpx.AsyncClient() as client:
                result = await _call_gemini(client, fallback_prompt, temperature=0.7, max_tokens=8192)
                return result
        except Exception as e:
            print(f"  [ERROR] Fallback generation failed: {e}")
            return None

    # ========== STAGE 2: Targeted Knowledge Base Search ==========
    print("  [Stage 2] Searching knowledge base based on market direction...")
    stage2_knowledge = ""
    try:
        from app.services.rag_engine import RAGEngine

        direction = stage1_assessment.get('market_direction', 'neutral')
        if direction == 'bullish':
            search_queries = ["逢高調節 順勢操作 倉位控制"]
        elif direction == 'bearish':
            search_queries = ["停損 風險管理 反彈觀察"]
        else:
            search_queries = ["區間操作 觀望策略"]

        engine = RAGEngine()
        await engine.initialise()

        all_chunks = []
        seen_texts = set()
        for query in search_queries:
            try:
                chunks = await engine.search(query=query, top_k=5)
                for chunk in chunks:
                    if chunk.text[:50] not in seen_texts:
                        seen_texts.add(chunk.text[:50])
                        all_chunks.append(chunk.text)
            except Exception:
                continue

        if all_chunks:
            stage2_knowledge = "\n\n".join(all_chunks[:8])
            print(f"  [Stage 2] Retrieved {len(all_chunks)} targeted knowledge chunks ({len(stage2_knowledge)} chars)")
        else:
            print("  [Stage 2] No targeted knowledge found")
    except Exception as e:
        print(f"  [Stage 2] Knowledge search failed: {e}")

    # Combine original knowledge with Stage 2 targeted knowledge
    combined_knowledge = knowledge_section
    if stage2_knowledge:
        combined_knowledge = f"{knowledge_section}\n\n--- 針對性策略參考 ---\n{stage2_knowledge}"

    # ========== STAGE 3: Generate Final Report ==========
    print("  [Stage 3] Generating final report with direction constraint...")

    # Build the MANDATORY direction constraint
    direction = stage1_assessment.get('market_direction', 'neutral')
    tw_change = stage1_assessment.get('tw_change_pct', 0)
    key_events = stage1_assessment.get('key_events', [])
    inst_flow = stage1_assessment.get('institutional_flow', '')

    direction_labels = {
        'bullish': '多方/上漲',
        'bearish': '空方/下跌',
        'neutral': '中性/盤整'
    }
    direction_label = direction_labels.get(direction, '中性/盤整')

    if direction == 'bullish':
        mandatory_line = (
            f"MANDATORY: 今日為多方格局 ({tw_change:+.2f}%)。"
            f"你必須先肯定多方動能與漲勢，再適度帶入逢高順勢調節的風險提醒。"
        )
    elif direction == 'bearish':
        mandatory_line = (
            f"MANDATORY: 今日為空方格局 ({tw_change:+.2f}%)。"
            f"你必須先說明下跌事實與風險，再帶入停損與反彈觀察建議。"
        )
    else:
        mandatory_line = (
            f"MANDATORY: 今日為中性盤整格局 ({tw_change:+.2f}%)。"
            f"你必須以區間操作與觀望策略為主軸撰寫報告。"
        )

    stage1_summary = (
        f"## Stage 1 市場評估結果\n"
        f"- 盤態方向: {direction_label}\n"
        f"- 漲跌幅: {tw_change:+.2f}%\n"
        f"- 關鍵觀察: {'; '.join(key_events)}\n"
        f"- 法人動向: {inst_flow}\n"
    )

    stage3_prompt = (
        f"⚠️ {mandatory_line}\n\n"
        "# Role & Tone\n"
        "你是一位專業、客觀且具備實戰經驗的台灣股市首席分析師。報告應兼具數據精準度、高可讀性與實用操作指引。\n\n"
        "# Core Execution Rules\n"
        "1. 報告長度：總輸出字數嚴格控制在 800-1000 字。說話直奔主題、精簡贅字，確保完整產出到操作建議與免責聲明。\n"
        "2. 盤態與中長期語氣調和：當日大漲時先肯定多方動能，再以「逢高順勢調節/注意高檔風險」帶出中長期警示。嚴禁在大漲日宣告市場極度悲觀。\n"
        "3. 數據格式化：金額大於億一律四捨五入換算為億元或兆元（保留小數點後1-2位）。絕對禁止輸出原始多位數數字。\n"
        "4. 防幻覺：指數點位與前一交易日維持連續性，絕對禁止捏造偏離現況超過10%的數字。\n"
        "5. 隱藏系統語言：絕對禁止提及「知識庫」「投資框架」「新聞列表為選單」「無具體新聞」等。新聞不足時直接以「從量價結構與籌碼動向觀察」帶過。\n"
        "6. 技術面白話化：MA5=5日均線/極短線成本, MA20=20日均線/月線。\n"
        "7. 報告末尾必須包含：倉位控制建議與具體停損/觀察點位。\n\n"
        f"{stage1_summary}\n"
        f"# 市場數據\n{tw_section}\n\n{us_section}\n\n{news_section}\n\n"
        f"# 投資知識參考\n{combined_knowledge}\n\n"
        "# 輸出格式\n"
        "請依序產出：1.台股摘要 2.美股狀況 3.趨勢分析 4.操作建議(含倉位與停損位) 5.免責聲明\n"
        "❗ 總字數不得超過1000字。必須完整產出到免責聲明。"
    )

    try:
        async with httpx.AsyncClient() as client:
            result = await _call_gemini(client, stage3_prompt, temperature=0.7, max_tokens=8192)
            if result:
                print(f"  [Stage 3] Report generated successfully ({len(result)} chars)")
            else:
                print("  [Stage 3] All models failed")
            return result
    except Exception as e:
        print(f"  [ERROR] Failed to generate report: {e}")
        return None

async def send_telegram(msg):
    """Send message to Telegram, splitting if >4000 chars."""
    msg_hash = get_message_hash(msg)
    sent_hashes = load_sent_hashes()

    if msg_hash in sent_hashes:
        print("  [INFO] Message already sent today, skipping duplicate.")
        return True

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Split message if too long
    messages = []
    if len(msg) > 4000:
        parts = []
        current = ""
        for line in msg.split('\n'):
            if len(current) + len(line) + 1 > 4000:
                parts.append(current)
                current = line
            else:
                current = current + '\n' + line if current else line
        if current:
            parts.append(current)
        messages = parts
    else:
        messages = [msg]

    try:
        async with httpx.AsyncClient() as client:
            for i, part in enumerate(messages):
                payload = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': part,
                    'parse_mode': 'Markdown'
                }
                resp = await client.post(url, json=payload, timeout=30)
                if resp.status_code != 200:
                    # Retry without markdown if parse fails
                    payload['parse_mode'] = 'HTML'
                    resp = await client.post(url, json=payload, timeout=30)
                    if resp.status_code != 200:
                        del payload['parse_mode']
                        resp = await client.post(url, json=payload, timeout=30)

                if resp.status_code == 200:
                    print(f"  [OK] Telegram message part {i+1}/{len(messages)} sent.")
                else:
                    print(f"  [ERROR] Telegram send failed: {resp.status_code} - {resp.text}")
                    return False

                # Small delay between parts
                if i < len(messages) - 1:
                    await asyncio.sleep(1)

        save_sent_hash(msg_hash)
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to send Telegram message: {e}")
        return False


async def store_to_knowledge(text):
    """Store analysis in knowledge base via Angelina /learn endpoint."""
    try:
        today_str = datetime.now(TW_TZ).strftime('%Y-%m-%d')
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ANGELINA_URL}/chat",
                json={
                    "message": f"/learn [Daily Analysis {today_str}] " + text[:1500],
                    "session_id": "daily-analysis-store",
                    "language": "zh-TW",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                print(f"  [OK] Analysis stored in knowledge base for {today_str}")
                return True
            else:
                print(f"  [WARN] Store returned status {resp.status_code}")
                return False
    except Exception as e:
        print(f"  [ERROR] Failed to store in knowledge base: {e}")
        return False

async def main():
    """Main orchestration function."""
    print("=" * 60)
    print(f"📊 Daily Market Analysis - {datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Step 1: Fetch market data
    print("\n[1/6] Fetching market data...")
    async with httpx.AsyncClient() as client:
        print("  Fetching Taiwan stock data...")
        tw_data = await fetch_twse_daily(client)
        print(
            f"  ✓ Taiwan data: summary={'yes' if tw_data.get('monthly_summary') else 'no'}, "
            f"gainers={len(tw_data.get('top_gainers', []))}, "
            f"institutional={len(tw_data.get('institutional', []))}"
        )

        print("  Fetching US market data...")
        us_data = await fetch_us_market(client)
        available_us = [k for k, v in us_data.items() if v]
        print(f"  ✓ US data: {', '.join(available_us) if available_us else 'none available'}")

        print("  Fetching news headlines...")
        news = await fetch_news(client)
        print(f"  ✓ News: {len(news)} headlines")

    market_data = {
        'taiwan': tw_data,
        'us': us_data,
        'news': news
    }

    # Step 2: Get knowledge base context
    print("\n[2/6] Querying knowledge base...")
    knowledge = await get_knowledge_context()
    if knowledge:
        print(f"  ✓ Knowledge context: {len(knowledge)} chars")
    else:
        print("  ⚠ No knowledge context available")

    # Step 3: Generate report
    print("\n[3/6] Generating AI analysis report...")
    report = await generate_report(market_data, knowledge)
    if not report:
        print("  ✗ Failed to generate report. Exiting.")
        return

    print(f"  ✓ Report generated: {len(report)} chars")

    # Step 4: Add header to report
    print("\n[4/6] Preparing final report...")
    today_str = datetime.now(TW_TZ).strftime('%Y年%m月%d日')
    final_report = f"📊 每日市場分析 - {today_str}\n\n{report}"
    print(f"  ✓ Final report ready: {len(final_report)} chars")

    # Step 5: Send to Telegram
    print("\n[5/6] Sending to Telegram...")
    success = await send_telegram(final_report)
    if success:
        print("  ✓ Report sent to Telegram successfully")
    else:
        print("  ✗ Failed to send to Telegram")

    # Step 6: Record to Google Sheets
    if SHEETS_ENABLED:
        print("\n[6/7] Recording to Google Sheets...")
        try:
            # Extract data for sheets
            tw_summary = market_data.get('taiwan', {}).get('monthly_summary', {})
            us_info = market_data.get('us', {})
            
            # Determine AI direction from report
            ai_direction = "中性"
            report_lower = report.lower() if report else ""
            if any(w in report_lower for w in ["看多", "偏多", "樂觀", "上漲"]):
                ai_direction = "看多"
            elif any(w in report_lower for w in ["看空", "偏空", "悲觀", "下跌"]):
                ai_direction = "看空"
            
            sheets_data = {
                '日期': datetime.now(TW_TZ).strftime('%Y-%m-%d'),
                '加權指數': tw_summary.get('收盤指數', tw_summary.get('\u6536\u76e4\u6307\u6578', 'N/A')),
                '漲跌幅(%)': tw_summary.get('漲跌百分比(%)', tw_summary.get('\u6f32\u8dcc\u767e\u5206\u6bd4(%)', 'N/A')),
                '成交量(億)': tw_summary.get('成交金額(元)', 'N/A'),
                'S&P 500': str(us_info.get('S&P 500', {}).get('price', 'N/A')) if us_info.get('S&P 500') else 'N/A',
                'NASDAQ': str(us_info.get('NASDAQ', {}).get('price', 'N/A')) if us_info.get('NASDAQ') else 'N/A',
                '道瓊': str(us_info.get('Dow Jones', {}).get('price', 'N/A')) if us_info.get('Dow Jones') else 'N/A',
                '三大法人淨買賣(億)': 'See sheet notes',
                'AI方向': ai_direction,
                '推撥狀態': '成功' if success else '失敗',
                '分析摘要': (report or '').replace('\n', ' ')[:500],
            }
            record_daily_data(sheets_data)
            print("  ✓ Recorded to Google Sheets")
        except Exception as e:
            print(f"  [ERROR] Sheets recording failed: {e}")
    else:
        print("\n[6/7] Google Sheets not available, skipping...")

    # Step 7: Store in knowledge base
    print("\n[7/7] Storing analysis in knowledge base...")
    stored = await store_to_knowledge(final_report)
    if stored:
        print("  ✓ Analysis stored in knowledge base")
    else:
        print("  ⚠ Could not store in knowledge base (non-critical)")

    print("\n" + "=" * 60)
    print("✅ Daily analysis complete!")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
