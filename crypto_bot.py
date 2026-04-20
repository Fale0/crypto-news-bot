import os
import feedparser
import re
from datetime import datetime, timedelta, timezone
import time
import requests
from flask import Flask, request, jsonify
import threading
from deep_translator import GoogleTranslator

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
last_update_id = 0

translator = GoogleTranslator(source='en', target='ru')

# ==================== ИСТОЧНИКИ НОВОСТЕЙ ====================
# Основные крипто-новости
MAIN_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptopotato.com/feed/",
    "https://bitcoinmagazine.com/feeds/news",
    "https://decrypt.co/feed",
    "https://www.newsbtc.com/feed/",
]

# Новости регуляторов (специальные разделы)
REGULATOR_FEEDS = [
    "https://cointelegraph.com/rss/tag/regulation",
    "https://www.coindesk.com/arc/outboundfeeds/rss/category/regulation/",
    "https://cryptopotato.com/category/regulation/feed/",
    "https://cointelegraph.com/rss/tag/sec",
    "https://cointelegraph.com/rss/tag/cftc",
]

# Ключевые слова для оценки важности
IMPORTANCE_KEYWORDS = {
    "high": ["hack", "exploit", "etf", "lawsuit", "regulation", "ban", "legal", "arrest", "billion", "million", "sec", "cftc", "fbi", "justice", "fine", "penalty"],
    "medium": ["launch", "partnership", "upgrade", "mainnet", "airdrop", "listing", "wallet"],
}

def clean_html(raw):
    return re.sub(r'<.*?>', '', raw)

def calculate_importance(title, description):
    text = (title + " " + description).lower()
    score = 5
    for kw in IMPORTANCE_KEYWORDS["high"]:
        if kw in text:
            score += 2
    for kw in IMPORTANCE_KEYWORDS["medium"]:
        if kw in text:
            score += 1
    if "bitcoin" in text or "btc" in text:
        score += 1
    if "ethereum" in text or "eth" in text:
        score += 1
    return min(10, max(1, score))

def translate_text(text):
    if not text or len(text.strip()) < 5:
        return text
    try:
        text_to_translate = text[:4000] if len(text) > 4000 else text
        return translator.translate(text_to_translate)
    except Exception as e:
        print(f"Ошибка перевода: {e}")
        return text

def fetch_news(feed_list, limit=5, source_name="main"):
    """Универсальная функция получения новостей"""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    
    for url in feed_list:
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
                
                # Переводим важные новости
                if importance >= 4:
                    title_ru = translate_text(title_en)
                    desc_ru = translate_text(desc_en[:400])
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
    
    # Сортируем по важности + дате
    articles.sort(key=lambda x: (x["importance"], x["date"]), reverse=True)
    
    # Убираем дубликаты
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    
    return unique[:limit]

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

def send_news_with_keyboard(chat_id, feed_list, count, title_message, source_type):
    """Отправляет новости и показывает клавиатуру"""
    send_message(chat_id, f"🔍 {title_message}\n⏳ Загружаю новости... (10-20 секунд)")
    
    news_list = fetch_news(feed_list, count, source_type)
    
    if not news_list:
        send_message(chat_id, "😕 *Новости не найдены*\n\nПопробуйте позже.")
        show_keyboard(chat_id)
        return
    
    for idx, news in enumerate(news_list, 1):
        if news["importance"] >= 8:
            imp_emoji = "🔴🔥"
        elif news["importance"] >= 6:
            imp_emoji = "🟠⚠️"
        elif news["importance"] >= 4:
            imp_emoji = "🟡📌"
        else:
            imp_emoji = "⚪📰"
        
        message = f"{imp_emoji} *{idx}. {news['title']}*\n\n"
        message += f"📝 {news['desc']}\n\n"
        message += f"📅 {news['date']} | 📰 {news['source']}\n"
        message += f"⭐ Важность: {news['importance']}/10\n\n"
        message += f"🔗 [Читать полностью]({news['link']})"
        
        send_message(chat_id, message)
        time.sleep(0.5)
    
    send_message(chat_id, f"✅ *Готово!* Показано {len(news_list)} новостей.")
    show_keyboard(chat_id)

def show_keyboard(chat_id):
    """Показывает клавиатуру с кнопками"""
    keyboard = {
        "keyboard": [
            ["📰 Топ-3 новости", "📚 Топ-5 новостей"],
            ["🏛️ Новости регуляторов"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "📱 *Выбери действие:*",
        "reply_markup": keyboard,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def bot_polling():
    global last_update_id
    print("✅ Бот запущен!")
    print("📌 Команды: /start, /news3, /news5, /regulators")
    print("🔘 Кнопки появятся после /start или любого действия")
    
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
                
                # Обработка команд и кнопок
                if text == "/start":
                    welcome = (
                        "🤖 *Криптоновостной бот v3.0*\n\n"
                        "📊 *Что умею:*\n"
                        "• Собираю новости из 10+ источников\n"
                        "• Оцениваю важность (от 1 до 10)\n"
                        "• Перевожу на русский\n\n"
                        "📌 *Команды:*\n"
                        "• `/start` — показать это меню\n"
                        "• `/news3` — топ-3 новости\n"
                        "• `/news5` — топ-5 новостей\n"
                        "• `/regulators` — новости регуляторов\n\n"
                        "💡 Или просто нажми на кнопки ниже!"
                    )
                    send_message(chat_id, welcome)
                    show_keyboard(chat_id)
                
                elif text == "/menu" or text == "🔘 Меню":
                    show_keyboard(chat_id)
                
                elif text == "/news3" or text == "📰 Топ-3 новости":
                    send_news_with_keyboard(chat_id, MAIN_FEEDS, 3, "📊 *Топ-3 самые важные новости криптомира*", "main")
                
                elif text == "/news5" or text == "📚 Топ-5 новостей":
                    send_news_with_keyboard(chat_id, MAIN_FEEDS, 5, "📊 *Топ-5 самых важных новостей криптомира*", "main")
                
                elif text == "/regulators" or text == "🏛️ Новости регуляторов":
                    send_news_with_keyboard(chat_id, REGULATOR_FEEDS, 5, "🏛️ *Новости крипторегуляторов (SEC, CFTC и др.)*", "regulators")
                
                elif text == "/health":
                    send_message(chat_id, "✅ Бот работает нормально!")
                
        except Exception as e:
            print(f"Ошибка в polling: {e}")
            time.sleep(5)

@app.route('/')
def index():
    return "🤖 Криптоновостной бот v3.0 работает! Отправьте /start в Telegram."

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
