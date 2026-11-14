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

    # YouTube Shorts uchun sarlavha 100 belgidan oshmasligi kerak
    if "#Shorts" not in title and "#shorts" not in title:
        short_title = f"{title[:90]} #Shorts"
    else:
        short_title = title[:100]

    body = {
        "snippet": {
            "title": short_title,
            "description": description,
            "tags": ["Tezkor", "Yangiliklar", "Shorts", "Reels"],
            "categoryId": "25"  # News & Politics
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[YouTube] Yuklanish: {int(status.progress() * 100)}%")

    print(f"[YouTube] Muvaffaqiyatli yuklandi! Video ID: {response.get('id')}")
    return response.get('id')

def get_instagram_reels_via_playwright(username, max_reels=5):
    print(f"[Playwright] Instagram @{username} profilidan Reels qidirilmoqda...")
    reels = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="uz-UZ"
        )
        page = context.new_page()
        try:
            url = f"https://www.instagram.com/{username}/reels/"
            print(f"[Playwright] Kirilmoqda: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            # Linklarni olish
            links = page.locator('a[href*="/reel/"], a[href*="/reels/"]').all()
            seen_ids = set()
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if not href:
                        continue
                    parts = [p.strip() for p in href.strip("/").split("/") if p.strip()]
                    reel_id = None
                    for idx, part in enumerate(parts):
                        if part in ("reel", "reels") and idx + 1 < len(parts):
                            reel_id = parts[idx + 1]
                            break
                    if reel_id and reel_id not in seen_ids:
                        seen_ids.add(reel_id)
                        reels.append({
                            "id": reel_id,
                            "url": f"https://www.instagram.com/reel/{reel_id}/"
                        })
                        if len(reels) >= max_reels:
                            break
                except Exception as ex:
                    print(f"[Playwright] Link o'qishda xatolik: {ex}")

            print(f"[Playwright] Topilgan Reels soni: {len(reels)}")
        except Exception as e:
            print(f"[Playwright] Reels ro'yxatini olishda xatolik: {e}")
        finally:
            browser.close()
    return reels

def download_reel(url, video_id):
    # 1. yt-dlp orqali sinab ko'rish
    output_template = f"downloads/{video_id}.%(ext)s"
    dl_cmd = [
        sys.executable, "-m", "yt_dlp",
        url,
        "-o", output_template,
        "--write-info-json",
        "--quiet",
        "--no-warnings"
    ]
    try:
        subprocess.run(dl_cmd, check=True)
        video_files = glob.glob(f"downloads/{video_id}.*")
        video_file = next((f for f in video_files if not f.endswith(".json")), None)
        if video_file and os.path.exists(video_file):
            title = "Tezkor Yangilik"
            description = "Tezkor OFFICIAL yangiliklari"
            info_file = f"downloads/{video_id}.info.json"
            if os.path.exists(info_file):
                try:
                    with open(info_file, "r", encoding="utf-8") as f:
                        info_data = json.load(f)
                    desc = info_data.get("description", "")
                    if desc:
                        description = desc
                        title = desc.split("
")[0][:90]
                except Exception:
                    pass
            return video_file, title, description
    except Exception as e:
        print(f"[yt-dlp] Yuklab bo'lmadi ({e}), Playwright fallback ishga tushmoqda...")

    # 2. Playwright orqali to'g'ridan-to'g'ri video src va sarlavhani olish
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            print(f"[Playwright] Reel sahifasiga kirilmoqda: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)

            video_el = page.locator("video").first
            video_src = video_el.get_attribute("src") if video_el.count() > 0 else None

            title = "Tezkor Yangilik"
            description = "Tezkor OFFICIAL yangiliklari"
            for sel in ['h1', 'span[dir="auto"]']:
                elements = page.locator(sel).all()
                for el in elements:
                    try:
                        txt = el.inner_text().strip()
                        if len(txt) > 20:
                            description = txt
                            title = txt.split("
")[0][:90]
                            break
                    except Exception:
                        pass
                if description != "Tezkor OFFICIAL yangiliklari":
                    break

            if video_src:
                video_file = f"downloads/{video_id}.mp4"
                resp = requests.get(video_src, stream=True, timeout=30)
                if resp.status_code == 200:
                    with open(video_file, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                    return video_file, title, description
        except Exception as e:
            print(f"[Playwright] Yuklab olishda xatolik: {e}")
        finally:
            browser.close()

    return None, None, None

def check_and_sync():
    print(f"[Sync] Instagram akkaunti tekshirilmoqda: @{INSTAGRAM_USERNAME}")
    history = load_history()

    os.makedirs("downloads", exist_ok=True)

    reels = get_instagram_reels_via_playwright(INSTAGRAM_USERNAME, max_reels=5)

    if not reels:
        print("[Sync] Playwright topa olmadi, yt-dlp fallback bilan tekshirilmoqda...")
        cmd = [
            sys.executable, "-m", "yt_dlp",
            f"https://www.instagram.com/{INSTAGRAM_USERNAME}/reels/",
            "--playlist-items", "1:5",
            "--dump-json",
            "--flat-playlist",
            "--quiet",
            "--no-warnings"
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            lines = proc.stdout.strip().split("
")
            for line in lines:
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    v_id = item.get("id") or item.get("url", "").split("/")[-2]
                    v_url = item.get("url") or f"https://www.instagram.com/reel/{v_id}/"
                    if v_id:
                        reels.append({"id": v_id, "url": v_url})
                except Exception:
                    pass
        except Exception as e:
            print(f"[Xato] yt-dlp fallback xatosi: {e}")

    youtube = None
    new_found = 0

    for item in reels:
        video_id = item["id"]
        url = item["url"]

        if video_id in history:
            print(f"[Tekshiruv] {video_id} avval yuklangan, o'tkazib yuborildi.")
            continue

        print(f"[Yangi video topildi!] ID: {video_id}, Manzil: {url}")

        video_file, title, description = download_reel(url, video_id)
        if not video_file or not os.path.exists(video_file):
            print(f"[Xato] Video yuklanmadi: {video_id}")
            continue

        if youtube is None:
            youtube = get_youtube_client()

        try:
            yt_id = upload_to_youtube(youtube, video_file, title, description)
            history.append(video_id)
            save_history(history)
            new_found += 1
            print(f"[Tayyor] Instagram {video_id} -> YouTube {yt_id}")
        except Exception as e:
            print(f"[Xato] YouTube'ga yuklashda xatolik yuz berdi: {e}")
        finally:
            for f in glob.glob(f"downloads/{video_id}.*"):
                try:
                    os.remove(f)
                except Exception:
                    pass

    print(f"[Tugatildi] Hammasi tekshirildi. Yangi yuklangan videolar soni: {new_found}")

if __name__ == "__main__":
    check_and_sync()
