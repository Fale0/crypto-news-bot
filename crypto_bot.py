import os
import feedparser
import re
from datetime import datetime, timedelta, timezone
import time
import requests
from flask import Flask, request, jsonify
import threading

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
last_update_id = 0

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

def clean_html(raw):
    return re.sub(r'<.*?>', '', raw)

def get_news():
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pub = entry.get("published_parsed")
                if not pub:
                    continue
                pub_dt = datetime.fromtimestamp(datetime(*pub[:6]).timestamp(), tz=timezone.utc)
                if pub_dt < cutoff:
                    continue
                articles.append({
                    "title": entry.get("title", "Без заголовка"),
                    "link": entry.get("link", "#"),
                    "desc": clean_html(entry.get("description", ""))[:250],
                    "date": pub_dt.strftime("%d.%m.%Y %H:%M"),
                    "source": feed.feed.get("title", url.split("/")[2]),
                })
        except:
            pass
    articles.sort(key=lambda x: x["date"], reverse=True)
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    return unique[:3]

def send(chat_id, text, preview=True):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": not preview
        }, timeout=30)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def bot_polling():
    global last_update_id
    print("Бот запущен и ожидает команды /news")
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id+1}&timeout=30"
            resp = requests.get(url, timeout=35)
            updates = resp.json()

            for update in updates.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if text == "/start":
                    send(chat_id, "👋 Привет! Отправь /news для получения 3 главных новостей криптомира.")
                elif text == "/news":
                    send(chat_id, "🔍 Ищу новости... Подождите 5-10 секунд.")
                    news = get_news()
                    if not news:
                        send(chat_id, "😕 Новости не найдены. Попробуйте позже.")
                    else:
                        for i, n in enumerate(news, 1):
                            msg_text = f"📰 *{i}. {n['title']}*\n\n{n['desc']}\n\n📅 {n['date']}\n📰 {n['source']}\n\n[Читать полностью]({n['link']})"
                            send(chat_id, msg_text, preview=False)
                        send(chat_id, "🚀 Это 3 главные новости!")
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)

@app.route('/')
def index():
    return "Бот работает! Отправьте /news в Telegram."

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    # Запускаем веб-сервер для health check
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
