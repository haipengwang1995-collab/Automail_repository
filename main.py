import os
import re
import html
import json
import smtplib
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from pathlib import Path

# =========================
# Basic Config
# =========================

BEIJING_TZ = timezone(timedelta(hours=8))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

QQ_EMAIL = os.getenv("QQ_EMAIL")
QQ_EMAIL_AUTH_CODE = os.getenv("QQ_EMAIL_AUTH_CODE")
RECIPIENT_EMAILS = os.getenv("RECIPIENT_EMAILS") or os.getenv("RECIPIENT_EMAIL")

MAX_NEWS_ITEMS_FOR_AI = 120
MAX_FINAL_ITEMS = 10

PROMPT_DIR = Path(__file__).parent / "prompts"

# =========================
# RSS Sources
# Some RSS links may change over time.
# If one source fails, the script will continue.
# =========================
RSS_FEEDS = [
    # =========================
    # Global business / economy
    # =========================
    {
        "source": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml"
    },
    {
        "source": "AP Business",
        "url": "https://apnews.com/hub/business?output=rss"
    },
    {
        "source": "CNBC Economy",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"
    },
    {
        "source": "CNBC Finance",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"
    },
    {
        "source": "NPR Business",
        "url": "https://feeds.npr.org/1006/rss.xml"
    },
    {
        "source": "The Guardian Business",
        "url": "https://www.theguardian.com/uk/business/rss"
    },

    # =========================
    # Financial Times public RSS
    # =========================
    {
        "source": "Financial Times - Global Economy",
        "url": "https://www.ft.com/global-economy?format=rss"
    },
    {
        "source": "Financial Times - Markets",
        "url": "https://www.ft.com/markets?format=rss"
    },
    {
        "source": "Financial Times - China",
        "url": "https://www.ft.com/china?format=rss"
    },
    {
        "source": "Financial Times - World",
        "url": "https://www.ft.com/world?format=rss"
    },

    # =========================
    # The Economist public RSS
    # =========================
    {
        "source": "The Economist - Finance & Economics",
        "url": "https://www.economist.com/finance-and-economics/rss.xml"
    },
    {
        "source": "The Economist - Business",
        "url": "https://www.economist.com/business/rss.xml"
    },
    {
        "source": "The Economist - China",
        "url": "https://www.economist.com/china/rss.xml"
    },

    # =========================
    # Asia / China
    # =========================
    {
        "source": "Nikkei Asia",
        "url": "https://asia.nikkei.com/rss/feed/nar"
    },
    {
        "source": "South China Morning Post - Business",
        "url": "https://www.scmp.com/rss/92/feed"
    },
    {
        "source": "South China Morning Post - Economy China",
        "url": "https://www.scmp.com/rss/318208/feed"
    },
    {
        "source": "Caixin Global",
        "url": "https://www.caixinglobal.com/rss/"
    },

    # =========================
    # International institutions
    # =========================
    {
        "source": "IMF News",
        "url": "https://www.imf.org/external/rss/news.xml"
    },
    {
        "source": "World Bank News",
        "url": "https://www.worldbank.org/en/news/all?format=rss"
    },
    {
        "source": "BIS Press Releases",
        "url": "https://www.bis.org/list/press_releases/index.rss"
    },

    # =========================
    # Central banks / official sources
    # =========================
    {
        "source": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml"
    },

    # =========================
    # Google News RSS - broader coverage
    # These help diversify sources.
    # Links may be Google redirect links.
    # =========================
    {
        "source": "Google News - Global Economy",
        "url": "https://news.google.com/rss/search?q=global%20economy%20when:1d&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "source": "Google News - China Economy",
        "url": "https://news.google.com/rss/search?q=China%20economy%20when:1d&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "source": "Google News - Central Banks",
        "url": "https://news.google.com/rss/search?q=central%20bank%20interest%20rates%20inflation%20when:1d&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "source": "Google News - Trade and Tariffs",
        "url": "https://news.google.com/rss/search?q=global%20trade%20tariffs%20supply%20chain%20when:1d&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "source": "Google News - Energy Economy",
        "url": "https://news.google.com/rss/search?q=energy%20oil%20gas%20economy%20when:1d&hl=en-US&gl=US&ceid=US:en"
    },
    {
        "source": "Google News - IMF World Bank OECD",
        "url": "https://news.google.com/rss/search?q=IMF%20OR%20World%20Bank%20OR%20OECD%20global%20economy%20when:1d&hl=en-US&gl=US&ceid=US:en"
    }
]

# =========================
# Helpers
# =========================

def load_prompt(filename):
    """
    Load a prompt template from the prompts directory.

    Args:
        filename: Prompt filename, e.g. "system.md" or "user.md"

    Returns:
        Prompt content as a UTF-8 string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
        RuntimeError: If the prompt file is empty.
    """

    prompt_path = PROMPT_DIR / filename

    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8").strip()

    if not content:
        raise RuntimeError(f"Prompt file is empty: {prompt_path}")

    return content



def now_beijing():
    return datetime.now(BEIJING_TZ)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title)
    return title[:120]


def parse_entry_date(entry):
    """
    Return datetime in UTC if available, otherwise None.
    """
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_news():
    """
    Fetch RSS entries from predefined sources.
    """
    all_items = []
    seen = set()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)

    for feed in RSS_FEEDS:
        source = feed["source"]
        url = feed["url"]

        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"[WARN] Failed to parse {source}: {e}")
            continue

        for entry in parsed.entries[:30]:
            title = clean_text(getattr(entry, "title", ""))
            link = clean_text(getattr(entry, "link", ""))
            summary = clean_text(getattr(entry, "summary", ""))

            if not title or not link:
                continue

            published_dt = parse_entry_date(entry)

            # If date exists and is too old, skip.
            # If no date, keep it because some RSS feeds omit dates.
            if published_dt and published_dt < cutoff:
                continue

            key = normalize_title(title)
            if key in seen:
                continue
            seen.add(key)

            published_str = ""
            if published_dt:
                published_str = published_dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M BJT")

            all_items.append({
                "id": len(all_items) + 1,
                "source": source,
                "title": title[:240],
                "summary": summary[:400],
                "link": link,
                "published": published_str
            })

    # Sort newer first when date available
    def sort_key(item):
        return item.get("published") or ""

    all_items = sorted(all_items, key=sort_key, reverse=True)

    return all_items[:MAX_NEWS_ITEMS_FOR_AI]


# def build_prompt(news_items):
#     today = now_beijing().strftime("%Y-%m-%d")

#     news_json = json.dumps(news_items, ensure_ascii=False, indent=2)

#     prompt = f"""
# You are a professional global economy news editor.

# Task:
# From the following RSS news items, select up to {MAX_FINAL_ITEMS} of the most important global economic, financial, trade, central bank, inflation, energy, commodity, industrial policy, China economy, or geopolitical-economy news items.

# Selection requirements:
# 1. Prioritize credible and mainstream sources.
# 2. Include China-related economic news if there is any meaningful China-related item.
# 3. Try to avoid selecting more than 2 items from the same source, unless the news is exceptionally important.
# 4. Try to cover several categories when possible:
#    - China economy
#    - US economy / Federal Reserve
#    - Europe economy / ECB
#    - Global trade and supply chains
#    - Energy and commodities
#    - International institutions such as IMF, World Bank, OECD, BIS
#    - Major industrial policy or geopolitical-economy developments
# 5. Avoid duplicate or near-duplicate stories.
# 6. Do not invent facts.
# 7. Use only the given news items.
# 8. Select items by their original "id".
# 9. Do not provide investment advice, stock recommendations, trading advice, or price predictions.

# Output requirements:
# 1. Return valid JSON only.
# 2. Do not use Markdown.
# 3. Do not include source names or links in your output. The program will add original RSS sources and links later.
# 4. Every selected item must contain both English and Simplified Chinese.
# 5. The Chinese summary should be slightly more detailed than the English summary.
# 6. English summary: 2 concise sentences.
# 7. Chinese summary: 3 to 5 sentences, around 120 to 220 Chinese characters.
# 8. The Chinese summary should explain:
#    - what happened,
#    - why it matters for the economy,
#    - possible macroeconomic or policy relevance.
# 9. Do not include investment advice or asset price predictions.

# Output JSON format must be exactly:

# {{
#   "items": [
#     {{
#       "id": 1,
#       "english_title": "English title here",
#       "chinese_title": "中文标题在这里",
#       "english_summary": "English summary in 2 concise sentences.",
#       "chinese_summary": "中文摘要，3到5句，约120到220个中文字符。需要说明事件本身、经济意义和政策或宏观背景，但不能包含投资建议或价格预测。"
#     }}
#   ]
# }}

# Date: {today}
# Time: 08:00 Beijing Time

# News items:
# {news_json}
# """
#     return prompt.strip()


def build_prompt(news_items):
    today = now_beijing().strftime("%Y-%m-%d")

    news_json = json.dumps(
        news_items,
        ensure_ascii=False,
        indent=2
    )

    template = load_prompt("user.md")

    return template.format(
        today=today,
        MAX_FINAL_ITEMS=MAX_FINAL_ITEMS,
        news_json=news_json
    )

def call_deepseek(user_prompt):
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    system_prompt = load_prompt("system.md")

    url = f"{AI_BASE_URL}/chat/completions"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 8000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=90)

    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek API error {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def extract_json_from_ai(ai_text):
    """
    Extract JSON from AI response.
    Handles cases where the model wraps JSON in ```json ... ```.
    """
    text = ai_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No valid JSON object found in AI response.")

    json_text = text[start:end + 1]
    return json.loads(json_text)



def build_ai_email(ai_data, news_items):
    """
    Build final email using AI analysis but original RSS links.
    AI provides analysis fields.
    RSS provides source and URL to avoid hallucinated links.
    """

    today = now_beijing().strftime("%Y-%m-%d")

    item_map = {}
    for item in news_items:
        item_map[int(item["id"])] = item

    lines = []

    lines.append(
        f"Daily Global Economic Briefing｜全球经济新闻速览｜{today}"
    )
    lines.append("")

    lines.append(
        "For reference only. This briefing does not constitute financial, investment, legal, business, or compliance advice."
    )
    lines.append(
        "仅供参考。本简报不构成金融、投资、法律、商业或合规建议。"
    )
    lines.append("")


    selected_items = ai_data.get("items", [])[:MAX_FINAL_ITEMS]

    count = 0

    for ai_item in selected_items:

        try:
            item_id = int(ai_item.get("id"))
        except Exception:
            continue


        original = item_map.get(item_id)

        if not original:
            continue


        count += 1


        lines.append("=" * 70)
        lines.append(
            f"{count}. {ai_item.get('chinese_title', '').strip()}"
        )
        lines.append("=" * 70)
        lines.append("")


        # English Title
        lines.append("English Title:")
        lines.append(
            ai_item.get(
                "english_title",
                original.get("title", "")
            ).strip()
        )
        lines.append("")


        # 中文摘要
        lines.append("【中文摘要】")
        lines.append(
            ai_item.get(
                "chinese_summary",
                ""
            ).strip()
        )
        lines.append("")

        importance = ai_item.get("importance_score", "")
        horizon = ai_item.get("investment_horizon", "").strip()

        risk_tags = ai_item.get("risk_tags", [])

        if isinstance(risk_tags, list):
            risk_tags = "｜".join(risk_tags)
        else:
            risk_tags = str(risk_tags)

        lines.append(
            f"重要性：{importance}/100    "
            f"投资周期：{horizon}    "
            f"风险标签：{risk_tags}"
        )

        lines.append("")


        # 传导机制
        lines.append("【传导机制】")
        lines.append(
            ai_item.get(
                "transmission_mechanism",
                ""
            ).strip()
        )
        lines.append("")


        affected_assets = ai_item.get("affected_assets", [])

        if isinstance(affected_assets, list):
            affected_assets = "｜".join(affected_assets)

        lines.append(
            f"影响资产：{affected_assets}"
        )

        lines.append("")


        # 行业影响
        lines.append("【行业影响】")
        lines.append(
            ai_item.get(
                "sector_impact",
                ""
            ).strip()
        )
        lines.append("")


        # 宏观逻辑
        lines.append("【宏观逻辑】")
        lines.append(
            ai_item.get(
                "macro_reasoning",
                ""
            ).strip()
        )
        lines.append("")


        # 投资组合含义
        lines.append("【投资组合建议】")
        lines.append(
            ai_item.get(
                "portfolio_implication",
                ""
            ).strip()
        )
        lines.append("")


        # RSS 原始信息
        source = original.get("source", "")
        published = original.get("published", "")
        link = original.get("link", "")

        lines.append(
            f"来源：{source}"
        )

        if published:
            lines.append(
                f"发布时间：{published}"
            )

        lines.append(
            f"原文：{link}"
        )

        lines.append("")
        lines.append("-" * 80)
        lines.append("")


    if count == 0:
        raise ValueError(
            "AI returned no valid selected items."
        )


    return "\n".join(lines)



def build_fallback_email(news_items):
    """
    If AI call fails, send a simple non-AI RSS digest.
    """
    today = now_beijing().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"Daily Global Economic Briefing｜全球经济新闻速览｜{today}")
    lines.append("")
    lines.append("For reference only. This briefing does not constitute financial, investment, legal, business, or compliance advice.")
    lines.append("仅供参考。本简报不构成金融、投资、法律、商业或合规建议。")
    lines.append("")
    lines.append("AI summary failed, so this is a simple RSS-based fallback digest.")
    lines.append("AI 摘要生成失败，因此以下为基于 RSS 的简易备用列表。")
    lines.append("")

    for i, item in enumerate(news_items[:MAX_FINAL_ITEMS], start=1):
        lines.append(f"{i}. {item['title']}")
        if item.get("summary"):
            lines.append(f"Summary: {item['summary']}")
        lines.append(f"Source: {item['source']}")
        if item.get("published"):
            lines.append(f"Published: {item['published']}")
        lines.append(f"Link: {item['link']}")
        lines.append("")

    return "\n".join(lines)

def parse_recipients(value):
    """
    Parse recipient emails from comma / semicolon separated string.
    Example:
    a@company.com,b@company.com;c@company.com
    """
    if not value:
        return []

    parts = re.split(r"[;,]", value)
    recipients = [p.strip() for p in parts if p.strip()]
    return recipients

def send_email(subject, body):
    if not QQ_EMAIL:
        raise RuntimeError("QQ_EMAIL is not set.")
    if not QQ_EMAIL_AUTH_CODE:
        raise RuntimeError("QQ_EMAIL_AUTH_CODE is not set.")
    if not RECIPIENT_EMAILS:
        raise RuntimeError("RECIPIENT_EMAILS or RECIPIENT_EMAIL is not set.")

    recipients = parse_recipients(RECIPIENT_EMAILS)

    if not recipients:
        raise RuntimeError("No valid recipient emails found.")

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((str(Header("Daily Economic Briefing", "utf-8")), QQ_EMAIL))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = Header(subject, "utf-8")

    smtp_server = "smtp.qq.com"
    smtp_port = 465

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(QQ_EMAIL, QQ_EMAIL_AUTH_CODE)
        server.sendmail(QQ_EMAIL, recipients, msg.as_string())

def main():
    today = now_beijing().strftime("%Y-%m-%d")
    subject = f"Daily Global Economic Briefing｜全球经济新闻速览｜{today}"

    news_items = []

    try:
        print("[INFO] Fetching news...")
        news_items = fetch_news()
        print(f"[INFO] Fetched {len(news_items)} news items.")
    except Exception as e:
        print(f"[ERROR] Failed to fetch news: {e}")
        body = f"""
Daily Global Economic Briefing｜全球经济新闻速览｜{today}

For reference only. This briefing does not constitute financial, investment, legal, business, or compliance advice.
仅供参考。本简报不构成金融、投资、法律、商业或合规建议。

Failed to fetch RSS news items today.
今天 RSS 新闻抓取失败。

Error:
{e}
""".strip()
        send_email(subject, body)
        return

    if not news_items:
        body = f"""
Daily Global Economic Briefing｜全球经济新闻速览｜{today}

For reference only. This briefing does not constitute financial, investment, legal, business, or compliance advice.
仅供参考。本简报不构成金融、投资、法律、商业或合规建议。

No RSS news items were fetched today.
今天未成功抓取到 RSS 新闻。
""".strip()
        send_email(subject, body)
        print("[INFO] Sent no-news email.")
        return

    try:
        print("[INFO] Calling DeepSeek...")
        prompt = build_prompt(news_items)
        ai_text = call_deepseek(prompt)

        print("[INFO] Parsing DeepSeek response...")
        ai_data = extract_json_from_ai(ai_text)

        print("[INFO] Building final email with original RSS links...")
        body = build_ai_email(ai_data, news_items)

    except Exception as e:
        print(f"[ERROR] DeepSeek failed or AI response parsing failed: {e}")
        body = build_fallback_email(news_items)

    print("[INFO] Sending email...")
    send_email(subject, body)
    print("[INFO] Email sent successfully.")


if __name__ == "__main__":
    main()