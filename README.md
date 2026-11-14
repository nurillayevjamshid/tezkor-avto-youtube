# Instagram to YouTube Auto Sync (Tezkor OFFICIAL)

Ushbu loyiha Instagram sahifasidagi (masalan, `@tezkor_official`) yangi Reels/videolarni avtomatik tarzda yuklab olib, YouTube kanalga **YouTube Shorts** sifatida yuklaydi.

Loyiha **GitHub Actions** orqali to'liq bulutda ishlaydi:
- Kompyuteringiz yoqiq turishi shart emas.
- Har 30 daqiqada avtomatik tekshiradi.
- Mutlaqo bepul (GitHub Actions bepul oylik 2000 daqiqasi yetadi).
- Hech qanday ma'lumot hajmi (MB) cheklovi yo'q.

---

## Fayllar tuzilishi
- `sync.py` — Instagram'ni tekshirish, yangi videoni yuklab olish va YouTube'ga joylash skripti.
- `history.json` — Avval yuklangan videolar ro'yxati (takroriy yuklanishning oldini oladi).
- `requirements.txt` — Kerakli kutubxonalar (`yt-dlp`, `google-api-python-client` va h.k.).
- `.github/workflows/sync.yml` — Har 30 daqiqada avtomatik ishga tushiruvchi GitHub Actions sozlamasi.

---

## GitHub Secrets sozlamalari
Repozitoriyangizda avtomatlashtirish ishlashi uchun quyidagi sozlamalarni kiriting:
1. Repozitoriyaga kiring: `https://github.com/nurillayevjamshid/tezkor-avto-youtube`
2. **Settings** ➔ **Secrets and variables** ➔ **Actions** bo'limiga o'ting.
3. **New repository secret** tugmasini bosib quyidagi 4 ta o'zgaruvchini qo'shing:

| Secret nomi | Tavsif |
|---|---|
| `INSTAGRAM_USERNAME` | Kuzatiladigan Instagram akkaunt nomi (masalan: `tezkor_official`) |
| `YOUTUBE_CLIENT_ID` | Google Cloud Console'dan olingan OAuth 2.0 Client ID |
| `YOUTUBE_CLIENT_SECRET` | Google Cloud Console'dan olingan Client Secret |
| `YOUTUBE_REFRESH_TOKEN` | YouTube kanalga video yuklash uchun olingan Refresh Token |
