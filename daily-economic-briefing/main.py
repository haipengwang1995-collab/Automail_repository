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


# =========================
# Basic Config
# =========================

BEIJING_TZ = timezone(timedelta(hours=8))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

QQ_EMAIL = os.getenv("QQ_EMAIL")
QQ_EMAIL_AUTH_CODE = os.getenv("QQ_EMAIL_AUTH_CODE")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

MAX_NEWS_ITEMS_FOR_AI = 80
MAX_FINAL_ITEMS = 10


# =========================
# RSS Sources
# Some RSS links may change over time.
# If one source fails, the script will continue.
# =========================

RSS_FEEDS = [
    # Global business / economy
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

    # Financial Times public RSS
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

    # The Economist public RSS
    {
        "source": "The Economist - Finance & Economics",
        "url": "https://www.economist.com/finance-and-economics/rss.xml"
    },
    {
        "source": "The Economist - Business",
        "url": "https://www.economist.com/business/rss.xml"
    },

    # Asia / China
    {
        "source": "Nikkei Asia",
        "url": "https://asia.nikkei.com/rss/feed/nar"
    },
    {
        "source": "South China Morning Post - Business",
        "url": "https://www.scmp.com/rss/92/feed"
    },
    {
        "source": "Caixin Global",
        "url": "https://www.caixinglobal.com/rss/"
    },

    # Multilateral institutions
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
]


# =========================
# Helpers
# =========================

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
                "source": source,
                "title": title[:240],
                "summary": summary[:500],
                "link": link,
                "published": published_str
            })

    # Sort newer first when date available
    def sort_key(item):
        return item.get("published") or ""

    all_items = sorted(all_items, key=sort_key, reverse=True)

    return all_items[:MAX_NEWS_ITEMS_FOR_AI]


def build_prompt(news_items):
    today = now_beijing().strftime("%Y-%m-%d")

    news_json = json.dumps(news_items, ensure_ascii=False, indent=2)

    prompt = f"""
You are a professional global economy news editor.

Task:
From the following RSS news items, select up to {MAX_FINAL_ITEMS} of the most important global economic, financial, trade, central bank, energy, commodity, industrial policy, or geopolitical-economy news items.

Requirements:
1. Output must be bilingual: English and Simplified Chinese.
2. Include China-related economic news if there is any meaningful item.
3. Each selected item must include:
   - Number
   - English title
   - 中文标题
   - English summary, 2-3 sentences
   - 中文摘要，2-3句
   - Source
   - Original link
4. Prioritize credible and mainstream sources.
5. Avoid duplicate or near-duplicate stories.
6. Do not provide stock recommendations, trading advice, investment advice, or price predictions.
7. Do not invent facts. Use only the given news items.
8. If fewer than 10 important items are available, output fewer than 10.
9. Format the result as a clean email briefing in Markdown-style plain text.
10. Add a short disclaimer at the top:
   "For reference only. This briefing does not constitute financial, investment, legal, business, or compliance advice."
   and Chinese equivalent.

Date: {today}
Time: 08:00 Beijing Time

News items:
{news_json}
"""
    return prompt.strip()


def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

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
                "content": "You are a careful and neutral global economy news editor. You summarize news without giving investment advice."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 4000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=90)

    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek API error {response.status_code}: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


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


def send_email(subject, body):
    if not QQ_EMAIL:
        raise RuntimeError("QQ_EMAIL is not set.")
    if not QQ_EMAIL_AUTH_CODE:
        raise RuntimeError("QQ_EMAIL_AUTH_CODE is not set.")
    if not RECIPIENT_EMAIL:
        raise RuntimeError("RECIPIENT_EMAIL is not set.")

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((str(Header("Daily Economic Briefing", "utf-8")), QQ_EMAIL))
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = Header(subject, "utf-8")

    smtp_server = "smtp.qq.com"
    smtp_port = 465

    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(QQ_EMAIL, QQ_EMAIL_AUTH_CODE)
        server.sendmail(QQ_EMAIL, [RECIPIENT_EMAIL], msg.as_string())


def main():
    today = now_beijing().strftime("%Y-%m-%d")
    subject = f"Daily Global Economic Briefing｜全球经济新闻速览｜{today}"

    print("[INFO] Fetching news...")
    news_items = fetch_news()
    print(f"[INFO] Fetched {len(news_items)} news items.")

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
        body = call_deepseek(prompt)
    except Exception as e:
        print(f"[ERROR] DeepSeek failed: {e}")
        body = build_fallback_email(news_items)

    print("[INFO] Sending email...")
    send_email(subject, body)
    print("[INFO] Email sent successfully.")


if __name__ == "__main__":
    main()