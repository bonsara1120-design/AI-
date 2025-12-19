import tweepy
import requests
import tempfile
import os
import csv
import time
import json
from datetime import datetime, timedelta, timezone

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ========================
# 環境変数
# ========================
API_KEY = os.environ.get("X_API_KEY")
API_SECRET = os.environ.get("X_API_SECRET")
ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

# ========================
# 設定
# ========================
SHEET_ID = "1XVucwTYjGeZOsqMSS1o6vm10XZ0wOBOH-TQIUFgpSHE"
SHEET_NAME = "シート1"   # ← 実際のシート名に合わせて
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

JST = timezone(timedelta(hours=9))
POST_WINDOW_SEC = 900     # ±15分
SLEEP_SEC = 60            # スレッド間隔

# ========================
# X 認証
# ========================
auth = tweepy.OAuth1UserHandler(
    API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET
)
api = tweepy.API(auth)
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_SECRET
)

# ========================
# Discord 通知
# ========================
def notify_discord(msg, is_error=False):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "embeds": [{
            "title": "❌ エラー" if is_error else "✅ 実行ログ",
            "description": msg,
            "color": 0xFF0000 if is_error else 0x00FF00,
            "timestamp": datetime.now(JST).isoformat()
        }]
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload)

# ========================
# Google Sheets 認証
# ========================
def get_worksheet():
    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# ========================
# 時刻判定
# ========================
def should_post(time_str):
    if not time_str:
        return False

    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            scheduled = datetime.strptime(time_str.strip(), fmt)
            break
        except ValueError:
            scheduled = None

    if not scheduled:
        return False

    scheduled = scheduled.replace(tzinfo=JST)
    now = datetime.now(JST)
    diff = (now - scheduled).total_seconds()

    return 0 <= diff <= POST_WINDOW_SEC

# ========================
# 画像DL
# ========================
def download_image(url):
    if not url:
        return None
    r = requests.get(url)
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    f.write(r.content)
    f.close()
    return f.name

# ========================
# スレッド投稿
# ========================
def post_thread(parent, reply1, reply2, image_url):
    media_ids = []

    if image_url:
        img = download_image(image_url)
        if img:
            media = api.media_upload(img)
            media_ids.append(media.media_id)
            os.unlink(img)

    res = client.create_tweet(
        text=parent,
        media_ids=media_ids if media_ids else None
    )
    parent_id = res.data["id"]

    if reply1:
        time.sleep(SLEEP_SEC)
        r1 = client.create_tweet(
            text=reply1,
            in_reply_to_tweet_id=parent_id
        )

    if reply2:
        time.sleep(SLEEP_SEC)
        client.create_tweet(
            text=reply2,
            in_reply_to_tweet_id=parent_id
        )

    return parent_id

# ========================
# メイン
# ========================
def main():
    notify_discord("🚀 自動投稿チェック開始")

    r = requests.get(CSV_URL)
    r.encoding = "utf-8-sig"
    rows = list(csv.reader(r.text.splitlines()))

    ws = get_worksheet()
    posted_any = False

    for idx, row in enumerate(rows[1:], start=2):
        post_time = row[1].strip()
        parent = row[2].strip()
        reply1 = row[3].strip() if len(row) > 3 else ""
        reply2 = row[4].strip() if len(row) > 4 else ""
        image_url = row[5].strip() if len(row) > 5 else ""
        posted = row[6].strip().lower() if len(row) > 6 else "no"

        if posted == "yes":
            continue
        if not should_post(post_time):
            continue

        try:
            parent_id = post_thread(parent, reply1, reply2, image_url)

            # ===== 書き戻し =====
            ws.update_cell(idx, 7, "Yes")       # Posted
            ws.update_cell(idx, 8, parent_id)   # Tweet ID

            notify_discord(
                f"📤 投稿成功（行 {idx}）\nTweet ID: {parent_id}"
            )
            posted_any = True
        except Exception as e:
            notify_discord(f"❌ 投稿失敗（行 {idx}）\n{e}", True)

        break  # 1実行1投稿

    if not posted_any:
        notify_discord("⏰ 対象投稿なし")

# ========================
if __name__ == "__main__":
    main()
