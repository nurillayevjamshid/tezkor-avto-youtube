import os
import re
import sys
import json
import glob
import urllib.parse
import subprocess
import requests
from playwright.sync_api import sync_playwright
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HISTORY_FILE = "history.json"
raw_username = os.environ.get("INSTAGRAM_USERNAME", "tezkor.official").strip()
# Agar secretda eski "tezkor_official" qolib ketgan bo'lsa, to'g'ri "tezkor.official" ga o'giramiz
if not raw_username or raw_username == "tezkor_official":
    INSTAGRAM_USERNAME = "tezkor.official"
else:
    INSTAGRAM_USERNAME = raw_username

INSTAGRAM_SESSIONID = (os.environ.get("INSTAGRAM_SESSIONID") or "").strip()
MAX_UPLOADS_PER_RUN = 3


def log(msg):
    print(msg, flush=True)


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
        raise ValueError("YouTube API Secrets to'liq emas!")

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )
    credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials)


def make_short_title(caption):
    if not caption:
        return "Tezkor Yangilik #Shorts"
    lines = [line.strip() for line in caption.splitlines() if line.strip()]
    first_para = lines[0] if lines else "Tezkor Yangilik"
    if "#shorts" in first_para.lower():
        return first_para[:100]
    return f"{first_para[:90].strip()} #Shorts"


def upload_to_youtube(youtube, video_path, title, description):
    log(f"[YouTube] Video yuklanmoqda: {title}")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description or "Tezkor OFFICIAL yangiliklari",
            "tags": ["Tezkor", "Yangiliklar", "Shorts", "Reels"],
            "categoryId": "25",  # News & Politics
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"[YouTube] Yuklanish: {int(status.progress() * 100)}%")

    vid_id = response.get("id")
    log(f"[YouTube] Muvaffaqiyatli yuklandi! Video ID: {vid_id} -> https://www.youtube.com/shorts/{vid_id}")
    return vid_id


def fetch_videos_via_api(username, sessionid):
    """Instagram Web Profile Info API orqali videolarni to'g'ridan-to'g'ri olish."""
    log(f"[API] @{username} profil ma'lumotlari olinmoqda...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "x-ig-app-id": "936619743392459",
        "Accept": "*/*",
        "Referer": f"https://www.instagram.com/{username}/",
    }
    cookies = {}
    if sessionid:
        cookies["sessionid"] = sessionid

    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=25)
        log(f"[API] HTTP status: {resp.status_code}")
        if resp.status_code != 200:
            log(f"[API] Javob boshi: {resp.text[:200]}")
            return []

        data = resp.json()
        user = data.get("data", {}).get("user")
        if not user:
            log("[API] User obyekti topilmadi.")
            return []

        edges = user.get("edge_owner_to_timeline_media", {}).get("edges", [])
        log(f"[API] Topilgan jami postlar: {len(edges)}")
        videos = []
        for edge in edges:
            node = edge.get("node", {})
            if not node.get("is_video"):
                continue
            shortcode = node.get("shortcode")
            video_url = node.get("video_url")
            cap_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            caption = cap_edges[0]["node"]["text"] if cap_edges else ""
            if shortcode:
                videos.append({
                    "id": shortcode,
                    "video_url": video_url,
                    "caption": caption,
                })
        log(f"[API] Ajratilgan videolar soni: {len(videos)}")
        return videos
    except Exception as e:
        log(f"[API Xato] {e}")
        return []


def fetch_videos_via_playwright(username, sessionid):
    """Playwright orqali profilni ochib, reel shortcodes va API javoblarini ushlab olish."""
    log(f"[Browser] @{username} sahifasi Playwright orqali ochilmoqda...")
    videos = []
    seen = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            if sessionid:
                cookie_val = sessionid
                context.add_cookies([
                    {
                        "name": "sessionid",
                        "value": cookie_val,
                        "domain": ".instagram.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                    }
                ])

            page = context.new_page()

            # Tarmoq javoblaridan GraphQL/API orqali kelgan videolarni ham ushlab qolamiz
            def handle_response(response):
                try:
                    if "web_profile_info" in response.url or "graphql" in response.url:
                        if response.status == 200 and "json" in (response.headers.get("content-type") or ""):
                            text = response.text()
                            for m in re.finditer(r'"code"\s*:\s*"([A-Za-z0-9_-]{8,15})"', text):
                                sc = m.group(1)
                                if sc not in seen:
                                    seen.add(sc)
                                    videos.append({"id": sc, "video_url": None, "caption": ""})
                            for m in re.finditer(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{8,15})"', text):
                                sc = m.group(1)
                                if sc not in seen:
                                    seen.add(sc)
                                    videos.append({"id": sc, "video_url": None, "caption": ""})
                except Exception:
                    pass

            page.on("response", handle_response)

            for target_url in [
                f"https://www.instagram.com/{username}/reels/",
                f"https://www.instagram.com/{username}/",
            ]:
                log(f"[Browser] Kirilmoqda: {target_url}")
                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                log(f"[Browser] Joriy URL: {page.url} | Sarlavha: {page.title()}")

                # Dialog/popup bo'lsa yopish
                for sel in ["[role='dialog'] svg[aria-label='Close']", "button:has-text('Not Now')", "button:has-text('Allow all cookies')"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

                anchors = page.locator("a[href*='/reel/'], a[href*='/p/']").all()
                log(f"[Browser] Sahifada topilgan havolalar: {len(anchors)}")
                for a in anchors:
                    try:
                        href = a.get_attribute("href") or ""
                        m = re.search(r"/(?:reel|p)/([A-Za-z0-9_-]+)", href)
                        if m:
                            sc = m.group(1)
                            if sc not in seen:
                                seen.add(sc)
                                videos.append({"id": sc, "video_url": None, "caption": ""})
                    except Exception:
                        pass

                if videos:
                    break

            browser.close()
    except Exception as e:
        log(f"[Browser Xato] {e}")

    log(f"[Browser] Jami ajratilgan kodlar: {[v['id'] for v in videos[:6]]}")
    return videos


def download_video(video_item, sessionid):
    video_id = video_item["id"]
    video_url = video_item.get("video_url")
    caption = video_item.get("caption", "")

    os.makedirs("downloads", exist_ok=True)
    mp4_path = f"downloads/{video_id}.mp4"

    # 1-usul: Agar API to'g'ridan-to'g'ri MP4 linkini bergan bo'lsa
    if video_url:
        try:
            log(f"[Yuklab olish] To'g'ridan-to'g'ri CDN'dan yuklanmoqda: {video_id}")
            r = requests.get(video_url, stream=True, timeout=60)
            if r.status_code == 200:
                with open(mp4_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 10000:
                    return mp4_path, caption
        except Exception as e:
            log(f"[CDN Xato] {e}")

    # 2-usul: yt-dlp orqali
    log(f"[Yuklab olish] yt-dlp orqali yuklanmoqda: {video_id}")
    reel_url = f"https://www.instagram.com/reel/{video_id}/"
    output_template = f"downloads/{video_id}.%(ext)s"
    dl_cmd = [
        sys.executable, "-m", "yt_dlp",
        reel_url,
        "-o", output_template,
        "--write-info-json",
        "--merge-output-format", "mp4",
        "--no-warnings",
    ]
    if sessionid:
        dl_cmd.extend(["--add-header", f"Cookie: sessionid={sessionid}"])

    res = subprocess.run(dl_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"[yt-dlp Xato] {res.stderr[:300]}")
        # Cookie'siz qayta urinish (ochiq reels uchun)
        dl_cmd_no_cookie = [
            sys.executable, "-m", "yt_dlp",
            reel_url,
            "-o", output_template,
            "--write-info-json",
            "--merge-output-format", "mp4",
            "--no-warnings",
        ]
        res2 = subprocess.run(dl_cmd_no_cookie, capture_output=True, text=True)
        if res2.returncode != 0:
            log(f"[yt-dlp Xato (cookie'siz)] {res2.stderr[:300]}")
            return None, caption

    video_files = glob.glob(f"downloads/{video_id}.*")
    video_file = next((f for f in video_files if not f.endswith(".json")), None)
    info_file = f"downloads/{video_id}.info.json"
    if not caption and os.path.exists(info_file):
        try:
            with open(info_file, "r", encoding="utf-8") as f:
                info_data = json.load(f)
                caption = info_data.get("description", "")
        except Exception:
            pass

    return video_file, caption


def check_and_sync():
    log(f"[Sync] Instagram akkaunti: @{INSTAGRAM_USERNAME} (Session cookie bor: {bool(INSTAGRAM_SESSIONID)})")
    history = load_history()

    # Avval tez va aniq API orqali urinib ko'ramiz
    videos = fetch_videos_via_api(INSTAGRAM_USERNAME, INSTAGRAM_SESSIONID)

    # Agar API bo'sh qaytarsa, Playwright orqali tekshiramiz
    if not videos:
        videos = fetch_videos_via_playwright(INSTAGRAM_USERNAME, INSTAGRAM_SESSIONID)

    if not videos:
        log("[Ogohlantirish] Hech qanday video topilmadi.")
        return

    # Faqat hali yuklanmagan eng yangi videolarni ajratib olamiz
    pending = [v for v in videos if v["id"] not in history]
    log(f"[Tekshiruv] Jami topildi: {len(videos)}, yangi (yuklanmagan): {len(pending)}")

    if not pending:
        log("[Tugatildi] Barcha oxirgi videolar avval yuklangan.")
        return

    youtube = get_youtube_client()
    log("[YouTube] API mijoz muvaffaqiyatli ulandi.")

    uploaded_count = 0
    for item in pending[:MAX_UPLOADS_PER_RUN]:
        vid_id = item["id"]
        log(f"[Jarayon] Yangi video: {vid_id}")
        video_file, caption = download_video(item, INSTAGRAM_SESSIONID)
        if not video_file or not os.path.exists(video_file):
            log(f"[Xato] {vid_id} yuklab olinmadi, o'tkazib yuborildi.")
            continue

        title = make_short_title(caption)
        try:
            upload_to_youtube(youtube, video_file, title, caption)
            history.append(vid_id)
            save_history(history)
            uploaded_count += 1
        except Exception as e:
            log(f"[YouTube Xato] {vid_id} yuklashda xatolik: {e}")
        finally:
            for f in glob.glob(f"downloads/{vid_id}.*"):
                try:
                    os.remove(f)
                except Exception:
                    pass

    log(f"[Tugatildi] Ushbu run'da yuklangan videolar soni: {uploaded_count}")


if __name__ == "__main__":
    check_and_sync()
