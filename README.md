# Quote Reel Bot

Turns stock clips into 10–15 s philosophy-quote reels and posts 5 a day to Instagram with a trending
sound. Everything runs on GitHub's servers, so your computer can stay off.

## How it works

| Piece | What it does |
|---|---|
| **Render reels** (Actions tab, run by hand) | Downloads the clips from your Google Drive folder, renders the quote reels, and stores them in this repo's **Releases → reels**. |
| **Post next reel** (runs automatically) | 5 times a day (08:33, 12:33, 17:03, 20:33, 22:47 IST) it posts the next reel with a trending sound and records it in `queue.json`. |
| `config.json` | Page handle, captions, hashtags, audio settings, text style. |
| `quotes.csv` | 148 quotes. Edit freely. |
| `post_log.txt` | Every post, the sound used, and any errors. |

## Setup checklist

1. **Instagram:** Creator (or Business) account, linked to a Facebook Page.
2. **Meta app + token:** see "Getting the Instagram token" below. You end up with two values.
3. **Repo secrets:** Settings → Secrets and variables → Actions → New repository secret:
   - `IG_USER_ID`
   - `IG_ACCESS_TOKEN`
4. **Render:** Actions → *Render reels* → Run workflow. 150 clips take about 30–60 min.
5. **Test post:** Actions → *Post next reel* → Run workflow. Check the reel on Instagram.
6. Done. It posts by itself from now on. When `post_log.txt` says fewer than 10 are left, run *Render reels* again.

## Getting the Instagram token

1. developers.facebook.com → My Apps → **Create App** → type **Business**. Add the **Instagram** product and pick
   **"API setup with Facebook login"**. Leave it in Development mode (no App Review needed for your own account).
2. **Tools → Graph API Explorer** → choose the app → **Generate Access Token** with:
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`.
3. **Tools → Access Token Debugger** → paste it → **Extend Access Token**.
4. Back in Graph API Explorer, with the extended token, run
   `me/accounts?fields=name,access_token,instagram_business_account`
   - `instagram_business_account.id` → **IG_USER_ID**
   - the Page's `access_token` → **IG_ACCESS_TOKEN** (made from an extended token, it doesn't expire)

## Changing things

- **Posting times / fewer posts a day:** edit the `cron:` lines in `.github/workflows/post.yml` (times are UTC = IST − 5:30).
- **Audio mood:** in `config.json` → `audio.search_queries`, e.g. `["slowed", "piano", "dark ambient"]`. Empty = whatever is trending.
  `pinned_audio_ids` = only use these exact sounds.
- **Text look:** `config.json` → `style`.
- **Pause posting:** Actions → *Post next reel* → ••• → Disable workflow.

## Running it on your own computer instead (optional)

`pip install -r requirements.txt gdown`, install ffmpeg, put the two values in a `.env` file (see `.env.example`), then:
`python fetch_drive.py <drive link>` → `python make_reels.py` → `python scheduler.py`.
