import os
import sys
import json
import glob
import subprocess
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HISTORY_FILE = "history.json"
INSTAGRAM_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "tezkor_official")

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
    return response.get("id")

def check_and_sync():
    print(f"[Sync] Instagram akkaunti tekshirilmoqda: @{INSTAGRAM_USERNAME}")
    history = load_history()
    
    os.makedirs("downloads", exist_ok=True)
    
    # yt-dlp yordamida oxirgi 5 ta post ma'lumotini olish
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
        lines = proc.stdout.strip().split("\n")
    except Exception as e:
        print(f"[Xato] Instagramdan ma'lumot olishda xatolik: {e}")
        return

    youtube = None
    new_found = 0

    for line in lines:
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue

        video_id = item.get("id") or item.get("url", "").split("/")[-2]
        url = item.get("url") or f"https://www.instagram.com/reel/{video_id}/"

        if video_id in history:
            print(f"[Tekshiruv] {video_id} avval yuklangan, o'tkazib yuborildi.")
            continue

        print(f"[Yangi video topildi!] ID: {video_id}, Manzil: {url}")
        
        # Videoni yuklab olish
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
                    title = desc.split("\n")[0][:90]

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

    print(f"[Tugatildi] Hammasi tekshirildi. Yangi yuklangan videolar soni: {new_found}")

if __name__ == "__main__":
    check_and_sync()
