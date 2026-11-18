import os
import re
import sys
import json
import glob
import subprocess
from datetime import datetime
from playwright.sync_api import sync_playwright
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HISTORY_FILE = "history.json"
INSTAGRAM_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "tezkor.official")
INSTAGRAM_SESSIONID = os.environ.get("INSTAGRAM_SESSIONID")

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
    return response.get("id")

def get_latest_reels_via_browser(username):
    print(f"[Browser] @{username} profilidagi so'nggi reels postlarini qidirish...")
    reels = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            
            # Agar sessionid bo'lsa, uni cookie sifatida qo'shamiz
            if INSTAGRAM_SESSIONID:
                print("[Browser] Instagram sessionid cookie qo'llanilmoqda...")
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                context.add_cookies([{
                    "name": "sessionid",
                    "value": INSTAGRAM_SESSIONID,
                    "domain": ".instagram.com",
                    "path": "/"
                }])
                page = context.new_page()
            else:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()

            url = f"https://www.instagram.com/{username}/"
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            
            # Login modal yoki cookie banner chiqsa, uni yopishga urinish
            try:
                for selector in ["[role='dialog'] svg[aria-label='Close']", "button:has-text('Not Now')", "button:has-text('Dismiss')", "button:has-text('Close')"]:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=1500):
                        btn.click()
            except Exception:
                pass

            # Sahifadagi barcha reel va post havolalarini topish
            anchors = page.locator("a[href*='/reel/'], a[href*='/p/']").all()
            for a in anchors:
                try:
                    href = a.get_attribute("href")
                    if href:
                        match = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]+)', href)
                        if match:
                            code = match.group(1)
                            if code not in reels:
                                reels.append(code)
                except Exception:
                    pass

            browser.close()
    except Exception as e:
        print(f"[Browser Xatolik] Playwright orqali sahifani yuklashda xatolik: {e}")
    return reels

def check_and_sync():
    print(f"[Sync] Instagram akkaunti tekshirilmoqda: @{INSTAGRAM_USERNAME}")
    history = load_history()
    
    os.makedirs("downloads", exist_ok=True)
    
    # 1. Playwright orqali reels havolalarini qidiramiz
    reels = get_latest_reels_via_browser(INSTAGRAM_USERNAME)
    print(f"[Reels] Topilgan postlar soni: {len(reels)} (Kodlar: {reels[:5]})")
    
    if not reels:
        print("[Ogohlantirish] Yangi postlar topilmadi.")
        return

    youtube = None
    new_found = 0

    for video_id in reels[:5]:
        url = f"https://www.instagram.com/reel/{video_id}/"

        if video_id in history:
            print(f"[Tekshiruv] {video_id} avval yuklangan, o'tkazib yuborildi.")
            continue

        print(f"[Yangi video topildi!] ID: {video_id}, Manzil: {url}")
        
        # yt-dlp yordamida videoni yuklab olish
        output_template = f"downloads/{video_id}.%(ext)s"
        dl_cmd = [
            sys.executable, "-m", "yt_dlp",
            url,
            "-o", output_template,
            "--write-info-json",
            "--quiet",
            "--no-warnings"
        ]
        if INSTAGRAM_SESSIONID:
            dl_cmd.extend(["--add-header", f"Cookie: sessionid={INSTAGRAM_SESSIONID}"])
        
        try:
            subprocess.run(dl_cmd, check=True)
        except Exception as e:
            print(f"[Xato] Videoni yuklab olishda muammo: {e}")
            continue

        # Yuklangan faylni topish
        video_files = glob.glob(f"downloads/{video_id}.*")
        video_file = next((f for f in video_files if not f.endswith(".json")), None)
        info_file = f"downloads/{video_id}.info.json"

        if not video_file or not os.path.exists(video_file):
            print(f"[Xato] Video fayli topilmadi: {video_id}")
            continue

        title = "Tezkor Yangilik"
        description = "Tezkor OFFICIAL yangiliklari"
        if os.path.exists(info_file):
            with open(info_file, "r", encoding="utf-8") as f:
                info_data = json.load(f)
                desc = info_data.get("description", "")
                if desc:
                    description = desc
                    # Faqat birinchi xatboshini olamiz va 90 belgidan oshirmaymiz
                    first_para = desc.split("\n")[0].strip()
                    title = first_para[:90]

        # YouTube ga yuklash
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
            # Fayllarni tozalash (joyni tejash uchun)
            for f in glob.glob(f"downloads/{video_id}.*"):
                try:
                    os.remove(f)
                except Exception:
                    pass

    print(f"[Tugatildi] Sinxronizatsiya yakunlandi. Yangi yuklangan videolar soni: {new_found}")

if __name__ == "__main__":
    check_and_sync()
