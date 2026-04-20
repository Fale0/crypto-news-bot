import os
import feedparser
import re
from datetime import datetime, timedelta, timezone
import time
import requests
from flask import Flask, request, jsonify
import threading
from deep_translator import GoogleTranslator
from collections import Counter
import random

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
last_update_id = 0

translator = GoogleTranslator(source='en', target='ru')

# ==================== РАСШИРЕННЫЕ ИСТОЧНИКИ ====================
RSS_FEEDS = {
    "main": [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cryptopotato.com/feed/",
        "https://bitcoinmagazine.com/feeds/news",
        "https://decrypt.co/feed",
        "https://www.newsbtc.com/feed/",
        "https://zycrypto.com/feed/",
        "https://beincrypto.com/feed/",
    ],
    "regulators": [
        "https://www.sec.gov/news/pressreleases.rss",  # SEC
        "https://www.cftc.gov/media/news.xml",        # CFTC
        "https://www.esma.europa.eu/press-news/rss.xml", # ESMA
        "https://www.bis.org/rss/all.rss.xml",        # Банк международных расчётов
    ]
}

# Ключевые слова для определения важности
IMPORTANCE_KEYWORDS = {
    "high": ["hack", "exploit", "etf", "lawsuit", "regulation", "ban", "legal", "arrest", "billion", "million"],
    "medium": ["launch", "partnership", "upgrade", "mainnet", "airdrop", "listing", "wallet"],
    "low": ["update", "community", "event", "podcast", "interview", "ama"]
}

def clean_html(raw):
    return re.sub(r'<.*?>', '', raw)

def calculate_importance(title, description):
    """Оценивает важность новости от 1 до 10"""
    text = (title + " " + description).lower()
    score = 5  # базовая важность
    
    for kw in IMPORTANCE_KEYWORDS["high"]:
        if kw in text:
            score += 2
    for kw in IMPORTANCE_KEYWORDS["medium"]:
        if kw in text:
            score += 1
    # Бонус за упоминание крупных криптовалют
    if "bitcoin" in text or "btc" in text:
        score += 1
    if "ethereum" in text or "eth" in text:
        score += 1
    if "solana" in text or "sol" in text:
        score += 0.5
    
    return min(10, max(1, score))

def fetch_news(source_type="main", limit=10):
    """Получает новости из указанного источника"""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    
    for url in RSS_FEEDS.get(source_type, []):
        try:
            print(f"Загружаю: {url}")
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:15]:
                pub = entry.get("published_parsed")
                if not pub:
                    continue
                
                pub_dt = datetime.fromtimestamp(
                    datetime(*pub[:6]).timestamp(), 
                    tz=timezone.utc
                )
                
                if pub_dt < cutoff:
                    continue
                
                title_en = entry.get("title", "Без заголовка")
                desc_en = clean_html(entry.get("description", "Нет описания"))[:500]
                link = entry.get("link", "#")
                
                importance = calculate_importance(title_en, desc_en)
                
                # Переводим только важные новости для экономии времени
                if importance >= 4:
                    title_ru = translator.translate(title_en)
                    desc_ru = translator.translate(desc_en[:400])
                else:
                    title_ru = title_en
                    desc_ru = desc_en[:400]
                
                articles.append({
                    "title": title_ru,
                    "title_en": title_en,
                    "link": link,
                    "desc": desc_ru[:350],
                    "date": pub_dt.strftime("%d.%m.%Y %H:%M"),
                    "source": feed.feed.get("title", url.split("/")[2]),
                    "importance": importance
                })
        except Exception as e:
            print(f"Ошибка {url}: {e}")
    
    # Сортируем по важности + свежести
    articles.sort(key=lambda x: (x["importance"], x["date"]), reverse=True)
    
    # Убираем дубликаты
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    
    return unique[:limit]

def format_news_message(news, index):
    """Форматирует новость с учётом важности"""
    # Эмодзи важности
    if news["importance"] >= 8:
        importance_emoji = "🔴🔥"
    elif news["importance"] >= 6:
        importance_emoji = "🟠⚠️"
    elif news["importance"] >= 4:
        importance_emoji = "🟡📌"
    else:
        importance_emoji = "⚪📰"
    
    message = f"{importance_emoji} *{index}. {news['title']}*\n\n"
    message += f"📝 {news['desc']}\n\n"
    message += f"📅 {news['date']} | 📰 {news['source']}\n"
    message += f"⭐ Важность: {news['importance']}/10\n\n"
    message += f"🔗 [Читать полностью]({news['link']})"
    
    return message

def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def send_news(chat_id, source_type, count, custom_text=None):
    """Отправляет новости из указанного источника"""
    send_message(chat_id, f"🔍 *Ищу новости...*\n📂 Источник: {source_type}\n⏳ Подождите 10-20 секунд.")
    
    news_list = fetch_news(source_type, count)
    
    if not news_list:
        send_message(chat_id, "😕 *Новости не найдены*\n\nПопробуйте позже.")
        return
    
    if custom_text:
        send_message(chat_id, custom_text)
    
    for idx, news in enumerate(news_list, 1):
        message = format_news_message(news, idx)
        send_message(chat_id, message)
        time.sleep(0.5)
    
    send_message(chat_id, f"✅ *Готово!* Показано {len(news_list)} новостей.")

def create_keyboard():
    """Создаёт клавиатуру с кнопками"""
    keyboard = [
        ["📰 Топ-3 новости", "📚 Топ-5 новостей"],
        ["🏦 Новости регуляторов"]
    ]
    return {"keyboard": keyboard, "resize_keyboard": True, "one_time_keyboard": False}

def bot_polling():
    global last_update_id
    print("✅ Бот запущен!")
    print("📌 Доступные команды: /start, /menu, /news3, /news5, /regulators")
    
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
                
                # Обработка команд
                if text == "/start":
                    welcome = (
                        "🤖 *Криптоновостной бот v2.0*\n\n"
                        "📊 *Что умею:*\n"
                        "• Собираю новости из 8+ источников\n"
                        "• Оцениваю важность (от 1 до 10)\n"
                        "• Перевожу на русский\n\n"
                        "📌 *Команды:*\n"
                        "• `/menu` — показать кнопки\n"
                        "• `/news3` — топ-3 новости\n"
                        "• `/news5` — топ-5 новостей\n"
                        "• `/regulators` — новости регуляторов\n\n"
                        "💡 Или просто нажми на кнопки в меню!"
                    )
                    send_message(chat_id, welcome)
                    send_message(chat_id, "🔽 Нажми на кнопку 'Меню' внизу экрана", parse_mode=None)
                    
                elif text == "/menu":
                    keyboard = create_keyboard()
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": "📱 *Выбери действие:*",
                        "reply_markup": keyboard,
                        "parse_mode": "Markdown"
                    }
                    requests.post(url, json=payload)
                    
                elif text == "/news3" or text == "📰 Топ-3 новости":
                    send_news(chat_id, "main", 3, "📊 *Топ-3 самые важные новости:*\n")
                    
                elif text == "/news5" or text == "📚 Топ-5 новостей":
                    send_news(chat_id, "main", 5, "📊 *Топ-5 самых важных новостей:*\n")
                    
                elif text == "/regulators" or text == "🏦 Новости регуляторов":
                    send_news(chat_id, "regulators", 5, "🏛️ *Новости крипторегуляторов:*\n")
                    
        except Exception as e:
            print(f"Ошибка в polling: {e}")
            time.sleep(5)

@app.route('/')
def index():
    return "🤖 Криптоновостной бот v2.0 работает! Отправьте /start в Telegram."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        print(f"Webhook: {update}")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Ошибка webhook: {e}")
        return jsonify({"ok": False})

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
