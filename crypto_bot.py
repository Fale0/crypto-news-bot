import os
import feedparser
import re
from datetime import datetime, timedelta, timezone
import time
import requests
from flask import Flask, request, jsonify
import threading
from deep_translator import GoogleTranslator
import urllib.parse
from openai import OpenAI

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
last_update_id = 0

# Настройка DeepSeek
if DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
    DEEPSEEK_AVAILABLE = True
    print("✅ DeepSeek API подключен")
else:
    DEEPSEEK_AVAILABLE = False
    print("⚠️ DeepSeek API ключ не найден")

translator = GoogleTranslator(source='en', target='ru')

# Московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

# ==================== ИСТОЧНИКИ НОВОСТЕЙ ====================
MAIN_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptopotato.com/feed/",
    "https://bitcoinmagazine.com/feeds/news",
    "https://decrypt.co/feed",
    "https://www.newsbtc.com/feed/",
]

REGULATOR_FEEDS = [
    "https://cointelegraph.com/rss/tag/regulation",
    "https://coindesk.com/arc/outboundfeeds/rss/category/regulation/?outputType=xml",
    "https://cryptonews.com/news/regulation/feed/",
    "https://cointelegraph.com/rss/tag/sec",
    "https://cointelegraph.com/rss/tag/cftc",
    "https://www.sec.gov/news/pressreleases.rss",
    "https://www.cftc.gov/media/news.xml",
]

# Ключевые слова для оценки важности
IMPORTANCE_KEYWORDS = {
    "high": ["hack", "exploit", "etf", "lawsuit", "regulation", "ban", "legal", "arrest", "billion", "million", "sec", "cftc", "fbi", "justice", "fine", "penalty"],
    "medium": ["launch", "partnership", "upgrade", "mainnet", "airdrop", "listing", "wallet"],
}

def clean_html(raw):
    return re.sub(r'<.*?>', '', raw)

def calculate_importance(title, description):
    """
    Оценка важности новости (от 1 до 10):
    - Базовый вес: 5
    +2 за ключевые слова высокой важности
    +1 за ключевые слова средней важности
    +1 за упоминание Bitcoin или Ethereum
    """
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

def analyze_with_deepseek(title, content):
    """Анализирует новость с помощью DeepSeek AI"""
    if not DEEPSEEK_AVAILABLE:
        return ""

    try:
        prompt = f"""Ты — крипто-аналитик. Сделай краткий анализ этой новости на русском языке.

Заголовок: {title}
Содержание: {content[:400]}

Напиши в формате:
💡 Суть: (одно предложение)
📊 Влияние: (позитивное/негативное/нейтральное)"""

        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150
        )
        return f"\n\n🤖 *DeepSeek:*\n{response.choices[0].message.content}"
    except Exception as e:
        print(f"Ошибка DeepSeek: {e}")
        return ""

def extract_image_from_article(link):
    """Пытается найти картинку на странице новости"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(link, timeout=15, headers=headers)

        patterns = [
            r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"',
            r'<meta[^>]*name="twitter:image"[^>]*content="([^"]+)"',
            r'<img[^>]*src="([^"]+)"[^>]*class="[^"]*featured[^"]*"',
        ]

        for pattern in patterns:
            match = re.search(pattern, response.text, re.IGNORECASE)
            if match:
                img_url = match.group(1)
                if img_url.startswith('http'):
                    return img_url
    except Exception as e:
        print(f"Ошибка извлечения картинки: {e}")
    return None

def generate_ai_image(title):
    """Генерирует картинку через бесплатный API Pollinations.ai"""
    try:
        prompt = f"crypto news, {title[:100]}"
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=768&nologo=true"

        response = requests.head(image_url, timeout=10)
        if response.status_code == 200:
            return image_url
    except Exception as e:
        print(f"Ошибка генерации AI картинки: {e}")

    # Резервные тематические картинки
    theme_images = {
        "bitcoin": "https://i.imgur.com/8qD4q4M.png",
        "ethereum": "https://i.imgur.com/Kp4zq8Z.png",
        "regulation": "https://i.imgur.com/2nJqj7L.png",
        "hack": "https://i.imgur.com/Xr5Kq9M.png",
        "default": "https://i.imgur.com/YxqJ5jK.png"
    }

    title_lower = title.lower()
    if "bitcoin" in title_lower or "btc" in title_lower:
        return theme_images["bitcoin"]
    elif "ethereum" in title_lower or "eth" in title_lower:
        return theme_images["ethereum"]
    elif "regul" in title_lower or "sec" in title_lower:
        return theme_images["regulation"]
    elif "hack" in title_lower or "exploit" in title_lower:
        return theme_images["hack"]
    else:
        return theme_images["default"]

def get_news_image(link, title):
    """Основная функция получения картинки для новости"""
    image_url = extract_image_from_article(link)
    if not image_url:
        image_url = generate_ai_image(title)
    return image_url

def fetch_news(feed_list, limit=5, source_name="main"):
    """Универсальная функция получения новостей с картинками"""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)

    for url in feed_list:
        try:
            print(f"Загружаю: {url}")
            feed = feedparser.parse(url)

            for entry in feed.entries[:15]:
                pub = entry.get("published_parsed")
                if not pub:
                    continue

                pub_dt_utc = datetime.fromtimestamp(
                    datetime(*pub[:6]).timestamp(),
                    tz=timezone.utc
                )

                if pub_dt_utc < cutoff:
                    continue

                pub_dt_msk = pub_dt_utc.astimezone(MOSCOW_TZ)

                title_en = entry.get("title", "Без заголовка")
                desc_en = clean_html(entry.get("description", "Нет описания"))[:500]
                link = entry.get("link", "#")

                importance = calculate_importance(title_en, desc_en)

                if importance >= 4:
                    title_ru = translate_text(title_en)
                    desc_ru = translate_text(desc_en[:400])
                else:
                    title_ru = title_en
                    desc_ru = desc_en[:400]

                image_url = None
                if 'media_content' in entry and entry.media_content:
                    image_url = entry.media_content[0].get('url')
                if not image_url:
                    image_url = get_news_image(link, title_en)

                articles.append({
                    "title": title_ru,
                    "title_en": title_en,
                    "link": link,
                    "desc": desc_ru[:350],
                    "date": pub_dt_msk.strftime("%d.%m.%Y %H:%M"),
                    "source": feed.feed.get("title", url.split("/")[2]),
                    "importance": importance,
                    "image_url": image_url
                })
        except Exception as e:
            print(f"Ошибка {url}: {e}")

    articles.sort(key=lambda x: (x["importance"], x["date"]), reverse=True)

    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    return unique[:limit]

def send_photo(chat_id, image_url, caption):
    """Отправляет фото с подписью"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=30)

        if response.status_code != 200:
            print(f"Ошибка фото: {response.text}")
            send_message(chat_id, caption)
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        send_message(chat_id, caption)

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
    """Отправляет новости с картинками и показывает клавиатуру"""
    send_message(chat_id, f"🔍 {title_message}\n⏳ Загружаю новости... (15-25 секунд)")

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

        caption = f"{imp_emoji} *{idx}. {news['title']}*\n\n"
        caption += f"📝 {news['desc']}\n\n"
        caption += f"📅 {news['date']} (МСК) | 📰 {news['source']}\n"
        caption += f"⭐ Важность: {news['importance']}/10\n\n"
        caption += f"🔗 [Читать полностью]({news['link']})"

        # Добавляем анализ DeepSeek
        if DEEPSEEK_AVAILABLE:
            ai_analysis = analyze_with_deepseek(news['title'], news['desc'])
            caption += ai_analysis

        if news.get("image_url"):
            send_photo(chat_id, news["image_url"], caption)
        else:
            send_message(chat_id, caption)

        time.sleep(0.5)

    send_message(chat_id, f"✅ *Готово!* Показано {len(news_list)} новостей с AI-картинками 🖼️")
    show_keyboard(chat_id)

def show_keyboard(chat_id):
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

def keep_alive():
    """Каждые 10 минут пингует свой health-эндпоинт, чтобы Render не усыплял бота"""
    bot_url = f"https://crypto-news-bot-v7aj.onrender.com/health"
    while True:
        time.sleep(10 * 60)
        try:
            response = requests.get(bot_url, timeout=10)
            print(f"🔄 Auto-ping: статус {response.status_code}")
        except Exception as e:
            print(f"❌ Auto-ping ошибка: {e}")

def bot_polling():
    global last_update_id
    print("✅ Бот запущен с DeepSeek AI и генерацией картинок!")
    print("📌 Команды: /start, /news3, /news5, /regulators")

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
                        "🤖 *Криптоновостной бот v6.0* 🖼️🤖\n\n"
                        "📊 *Что умею:*\n"
                        "• Собираю новости из 10+ источников\n"
                        "• **Оцениваю важность** (от 1 до 10)\n"
                        "• Перевожу на русский\n"
                        "• Генерирую AI-картинки\n"
                        "• **Анализирую новости через DeepSeek AI** 🧠\n\n"
                        "📌 *Методология оценки важности:*\n"
                        "• Базовая оценка: 5/10\n"
                        "• +2 за ключевые слова: хак, иск, регуляции, ETF, SEC\n"
                        "• +1 за партнёрства, запуски, листинги\n"
                        "• +1 за упоминание Bitcoin или Ethereum\n\n"
                        "📌 *Команды:*\n"
                        "• `/news3` — топ-3 новости\n"
                        "• `/news5` — топ-5 новостей\n"
                        "• `/regulators` — новости регуляторов\n\n"
                        "⏰ Новости только за последние 36 часов\n"
                        "🕒 Время указано московское (МСК)\n"
                        "♻️ *Бот работает 24/7*\n"
                        "🧠 *DeepSeek AI анализирует каждую новость*\n\n"
                        "💡 Нажми на кнопки ниже!"
                    )
                    send_message(chat_id, welcome)
                    show_keyboard(chat_id)

                elif text == "/news3" or text == "📰 Топ-3 новости":
                    send_news_with_keyboard(chat_id, MAIN_FEEDS, 3, "📊 *Топ-3 самые важные новости криптомира*", "main")

                elif text == "/news5" or text == "📚 Топ-5 новостей":
                    send_news_with_keyboard(chat_id, MAIN_FEEDS, 5, "📊 *Топ-5 самых важных новостей криптомира*", "main")

                elif text == "/regulators" or text == "🏛️ Новости регуляторов":
                    send_news_with_keyboard(chat_id, REGULATOR_FEEDS, 8, "🏛️ *Новости крипторегуляторов (SEC, CFTC и др.)*", "regulators")

                elif text == "/health":
                    send_message(chat_id, "✅ Бот работает нормально!\n🕒 Московское время\n📅 Новости за 36 часов\n♻️ Авто-пинг активен\n🧠 DeepSeek AI подключен")

        except Exception as e:
            print(f"Ошибка в polling: {e}")
            time.sleep(5)

@app.route('/')
def index():
    return "🤖 Криптоновостной бот v6.0 (DeepSeek AI + картинки) работает!"

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
    # Запускаем авто-пинг
    ping_thread = threading.Thread(target=keep_alive, daemon=True)
    ping_thread.start()
    print("🟢 Auto-ping активирован (каждые 10 минут)")

    # Запускаем бота
    bot_thread = threading.Thread(target=bot_polling, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
