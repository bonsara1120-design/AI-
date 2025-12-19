import tweepy
import requests
import tempfile
import os
import csv
import time
from datetime import datetime, timedelta, timezone

# ========================
# 環境変数
# ========================
API_KEY = os.environ.get('X_API_KEY')
API_SECRET = os.environ.get('X_API_SECRET')
ACCESS_TOKEN = os.environ.get('X_ACCESS_TOKEN')
ACCESS_SECRET = os.environ.get('X_ACCESS_SECRET')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')

# ========================
# X 認証
# ========================
auth = tweepy.OAuth1UserHandler(
    API_KEY,
    API_SECRET,
    ACCESS_TOKEN,
    ACCESS_SECRET
)
api = tweepy.API(auth)
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_SECRET
)

# ========================
# 設定
# ========================
SHEET_URL = "https://docs.google.com/spreadsheets/d/1XVucwTYjGeZOsqMSS1o6vm10XZ0wOBOH-TQIUFgpSHE/export?format=csv"
JST = timezone(timedelta(hours=9))
POST_WINDOW_SEC = 3600   # 1時間（最低）
SLEEP_SEC = 60          # 投稿間隔

# ========================
# Discord 通知
# ========================
def notify_discord(message, is_error=False):
    if not DISCORD_WEBHOOK_URL:
        return
    color = 0xFF0000 if is_error else 0x00FF00
    payload = {
        "embeds": [{
            "title": "❌ エラー" if is_error else "✅ 投稿成功",
            "description": message,
            "color": color,
            "timestamp": datetime.now(JST).isoformat()
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception:
        pass

# ========================
# 日付判定（完全版）
# ========================
def should_post(time_str):
    if not time_str:
        return False

    time_str = time_str.strip()
    now = datetime.now(JST)

    scheduled = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            scheduled = datetime.strptime(time_str, fmt)
            break
        except ValueError:
            continue

    if scheduled is None:
        return False

    scheduled = scheduled.replace(tzinfo=JST)
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
        try:
            img = download_image(image_url)
            media = api.media_upload(img)
            media_ids.append(media.media_id)
            os.unlink(img)
        except Exception:
            pass

    res_parent = client.create_tweet(
        text=parent,
        media_ids=media_ids if media_ids else None
    )
    parent_id = res_parent.data["id"]

    reply1_id = None
    reply2_id = None

    if reply1:
        time.sleep(SLEEP_SEC)
        res1 = client.create_tweet(
            text=reply1,
            in_reply_to_tweet_id=parent_id
        )
        reply1_id = res1.data["id"]

    if reply2:
        time.sleep(SLEEP_SEC)
        res2 = client.create_tweet(
            text=reply2,
            in_reply_to_tweet_id=reply1_id or parent_id
        )
        reply2_id = res2.data["id"]

    return parent_id, reply1_id, reply2_id

# ========================
# メイン処理
# ========================
def main():
    print("🚀 自動投稿チェック開始")
    r = requests.get(SHEET_URL)
    r.encoding = "utf-8-sig"
    rows = list(csv.reader(r.text.splitlines()))

    for idx, row in enumerate(rows[1:], start=2):
        # 列対応
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

        print(f"📤 投稿実行（行 {idx}）")

        try:
            p_id, r1_id, r2_id = post_thread(parent, reply1, reply2, image_url)
            msg = f"スレッド投稿完了\n親ID: {p_id}"
            print(f"✅ {msg}")
            notify_discord(msg, False)
        except Exception as e:
            err = f"投稿失敗（行 {idx}）: {e}"
            print(f"❌ {err}")
            notify_discord(err, True)

        break  # 1回の実行で1スレッドのみ

    print("⏰ 対象投稿なし")

# ========================
if __name__ == "__main__":
    main()
