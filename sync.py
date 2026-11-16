import os
import sys
import json
import glob
import subprocess
import time
import requests
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from playwright.sync_api import sync_playwright

HISTORY_FILE = "history.json"
DEFAULT_USER = "tezkor.official"
env_user = os.environ.get("INSTAGRAM_USERNAME", DEFAULT_USER).strip()
INSTAGRAM_USERNAME = DEFAULT_USER if env_user in ("tezkor_official", "") else env_user

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        raise ValueError("YouTube API hisob ma'lumotlari (Secrets) to'liq emas! YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET va YOUTUBE_REFRESH_TOKEN talab qilinadi.")

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials)

def upload_to_youtube(youtube, video_path, title, description):
    print(f"[YouTube] Video yuklanmoqda: {title}")
    if "#Shorts" not in title and "#shorts" not in title:
        short_title = f"{title[:90]} #Shorts"
    else:
        short_title = title[:100]

    body = {
        "snippet": {
            "title": short_title,
            "description": f"{description}\n\n#tezkor #yangiliklar #shorts",
            "tags": ["tezkor", "yangiliklar", "shorts", "tezkor_official"],
            "categoryId": "25"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[YouTube] Yuklanish jarayoni: {int(status.progress() * 100)}%")

    print(f"[YouTube] Muvaffaqiyatli yuklandi! Video ID: {response.get('id')}")
    return response.get('id')

def get_latest_reels_via_playwright(username, limit=3):
    print(f"[Playwright] @{username} profilidan Reels olinmoqda...")
    reels = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        profile_url = f"https://www.instagram.com/{username}/"
        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        links = page.locator('a[href*="/reel/"], a[href*="/p/"]').all()
        shortcodes = []
        for l in links:
            


            href = l.get_attribute("href") or ""
            parts = [p for p in href.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("reel", "p"):
                sc = parts[1]
                if sc not in shortcodes:
                    shortcodes.append(sc)
            elif len(parts) >= 3 and parts[1] in ("reel", "p"):
                sc = parts[2]
                if sc not in shortcodes:
                    shortcodes.append(sc)

        print(f"[Playwright] Topilgan post/reel shortcodes: {shortcodes[:limit]}")

        for sc in shortcodes[:limit]:
            reel_url = f"https://www.instagram.com/reel/{sc}/"
            try:
                page.goto(reel_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                video_el = page.locator("video").first
                video_src = None
                if video_el.is_visible(timeout=5000):
                    video_src = video_el.get_attribute("src")

                page_title = page.title()
                desc = page_title
                try:
                    h1 = page.locator("h1").first
                    if h1.is_visible(timeout=2000):
                        desc = h1.inner_text()
                except Exception:
                    pass

                reels.append({
                    "shortcode": sc,
                    "url": reel_url,
                    "video_url": video_src,
                    "caption": desc
                })
            except Exception as e:
                print(f"[Playwright] Postni ochishda xato ({sc}): {e}")

        browser.close()
    return reels

def download_video(url, output_path):
    print(f"[Download] Video yuklab olinmoqda: {url[:60]}...")
    resp = requests.get(url, stream=True, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"[Download] Saqlandi: {output_path}")

def main():
    print(f"=== Instagram to YouTube Sync boshlandi ({datetime.now()}) ===")
    history = load_history()
    print(f"Oldingi yuklangan videolar soni: {len(history)}")

    try:
        youtube = get_youtube_client()
        print("[YouTube] API mijoz muvaffaqiyatli ulandi.")
    except Exception as e:
        print(f"[YouTube XATO] API mijozni ishga tushirib bo'lmadi: {e}")
        sys.exit(1)

    reels = get_latest_reels_via_playwright(INSTAGRAM_USERNAME, limit=3)
    if not reels:
        print("[Instagram] Hech qanday reel/video topilmadi.")
        return

    new_count = 0
    for reel in reels:
        sc = reel["shortcode"]
        if sc in history:
            print(f"Post [{sc}] allaqachon yuklangan, o'tkazib yuboriladi.")
            continue

        video_url = reel.get("video_url")
        if not video_url:
            print(f"Post [{sc}] uchun video URL topilmadi, o'tkazib yuboriladi.")
            continue

        desc = reel.get("caption") or f"Tezkor yangilik {sc}"
        title_lines = [l.strip() for l in desc.splitlines() if l.strip()]
        title = title_lines[0] if title_lines else f"Tezkor Yangilik {sc}"
        if len(title) > 90:
            title = title[:87] + "..."

        temp_file = f"temp_{sc}.mp4"
        try:
            download_video(video_url, temp_file)
            yt_id = upload_to_youtube(youtube, temp_file, title, desc)
            history.append(sc)
            save_history(history)
            new_count += 1
            print(f"[SUCCESS] Post [{sc}] YouTube'ga muvaffaqiyatli yuklandi: https://youtu.be/{yt_id}")
            break
        except Exception as e:
            print(f"[XATO] Post [{sc}] yuklashda xatolik: {e}")
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    print(f"=== Yakunlandi. Yangi yuklangan videolar: {new_count} ta ===")

if __name__ == "__main__":
    main()
