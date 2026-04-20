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

# Создаём переводчик (один раз при запуске)
translator = GoogleTranslator(source='en', target='ru')

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

def clean_html(raw_html):
    """Удаляет HTML-теги из текста"""
    clean = re.compile(r'<.*?>')
    return re.sub(clean, '', raw_html)

def translate_text(text):
    """
    Переводит текст с английского на русский.
    Если перевод не удался, возвращает оригинал.
    """
    if not text or len(text.strip()) < 5:
        return text
    
    try:
        # Ограничиваем длину (Google Translate имеет лимит ~5000 символов)
        text_to_translate = text[:4000] if len(text) > 4000 else text
        translated = translator.translate(text_to_translate)
        return translated
    except Exception as e:
        print(f"Ошибка перевода: {e}")
        return text

def fetch_crypto_news():
    """Получает новости, переводит их на русский и возвращает список"""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    
    for url in RSS_FEEDS:
        try:
            print(f"Загружаю: {url}")
            feed = feedparser.parse(url)
            
            for entry in feed.entries[:10]:
                pub = entry.get("published_parsed")
                if not pub:
                    continue
                
                pub_dt = datetime.fromtimestamp(
                    datetime(*pub[:6]).timestamp(), 
                    tz=timezone.utc
                )
                
                if pub_dt < cutoff:
                    continue
                
                # Получаем оригинальные данные
                title_en = entry.get("title", "Без заголовка")
                desc_en = clean_html(entry.get("description", "Нет описания"))[:500]
                link = entry.get("link", "#")
                
                print(f"Перевожу: {title_en[:50]}...")
                
                # Переводим на русский
                title_ru = translate_text(title_en)
                desc_ru = translate_text(desc_en)
                
                # Ищем изображение
                image_url = None
                if 'media_content' in entry and entry.media_content:
                    image_url = entry.media_content[0].get('url')
                elif 'links' in entry:
                    for link_obj in entry.links:
                        if link_obj.get('type', '').startswith('image/'):
                            image_url = link_obj.get('href')
                            break
                
                articles.append({
                    "title": title_ru,
                    "title_en": title_en,
                    "link": link,
                    "desc": desc_ru[:350],
                    "desc_en": desc_en[:350],
                    "date": pub_dt.strftime("%d.%m.%Y %H:%M"),
                    "source": feed.feed.get("title", url.split("/")[2]),
                    "image_url": image_url
                })
        except Exception as e:
            print(f"Ошибка загрузки {url}: {e}")
    
    # Сортируем по дате
    articles.sort(key=lambda x: x["date"], reverse=True)
    
    # Убираем дубликаты
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    
    return unique[:3]

def send_photo(chat_id, image_url, caption):
    """Отправляет фото с подписью"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            send_message(chat_id, caption)
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        send_message(chat_id, caption)

def send_message(chat_id, text):
    """Отправляет текстовое сообщение"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def format_news_message(news, index):
    """Форматирует новость в красивое сообщение"""
    emojis = ["🔥", "📈", "💎", "🚀", "💰", "⚡️", "🎯", "🏆"]
    emoji = emojis[(index - 1) % len(emojis)]
    
    message = f"{emoji} *[{index}] {news['title']}*\n\n"
    message += f"📝 {news['desc']}\n\n"
    message += f"📅 *Дата:* {news['date']}\n"
    message += f"📰 *Источник:* {news['source']}\n\n"
    message += f"🔗 [Читать полностью]({news['link']})"
    
    # Показываем оригинал только если он сильно отличается
    if news['title_en'] and news['title_en'].lower() != news['title'].lower():
        message += f"\n\n_🌐 Оригинал: {news['title_en']}_"
    
    return message

def bot_polling():
    """Основной цикл бота"""
    global last_update_id
    print("✅ Бот запущен и ожидает команды /news")
    print("🌐 Переводчик настроен (английский → русский)")
    
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
                    welcome = (
                        "🤖 *Криптоновостной бот*\n\n"
                        "📰 Я собираю главные новости из мира криптовалют "
                        "и **перевожу их на русский язык**.\n\n"
                        "📌 *Команды:*\n"
                        "• `/news` — получить 3 главные новости\n"
                        "• `/start` — показать это сообщение\n\n"
                        "💡 *Совет:* новости приходят с картинками, "
                        "если они доступны в источнике."
                    )
                    send_message(chat_id, welcome)
                    
                elif text == "/news":
                    send_message(chat_id, "🔍 *Ищу свежие новости...*\n⏳ Это может занять 10-15 секунд.")
                    
                    news_list = fetch_crypto_news()
                    
                    if not news_list:
                        send_message(chat_id, "😕 *Новости не найдены*\n\nПопробуйте позже.")
                    else:
                        send_message(chat_id, f"✅ *Найдено {len(news_list)} новостей!*\n🔄 Перевожу на русский...")
                        
                        for idx, news in enumerate(news_list, 1):
                            caption = format_news_message(news, idx)
                            
                            if news.get("image_url"):
                                send_photo(chat_id, news["image_url"], caption)
                            else:
                                send_message(chat_id, caption)
                            
                            time.sleep(0.5)
                        
                        send_message(chat_id, "🚀 *Это 3 главные новости криптомира!*")
                        
        except Exception as e:
            print(f"Ошибка в polling: {e}")
            time.sleep(5)

@app.route('/')
def index():
    return "🤖 Криптоновостной бот работает! Отправьте /news в Telegram."

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        print(f"Webhook received: {update}")
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
