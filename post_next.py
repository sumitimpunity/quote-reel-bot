"""
post_next.py - publishes the next reel in queue.json to Instagram, with a trending sound.

    python post_next.py             # post the next reel
    python post_next.py --dry-run   # show what it would post and which audio it would pick
    python post_next.py --list-audio [search words]   # see trending / searched sounds the API offers

Needs two values in a .env file next to this script (see README):
    IG_USER_ID=1784...
    IG_ACCESS_TOKEN=EAAG...

Flow (Instagram Graph API, "Instagram API with Facebook Login"):
  1. GET /ig_audio          -> trending (or searched) sounds cleared for API use
  2. POST /{ig-user}/media  -> Reel container with audio_configuration, resumable upload
  3. upload the mp4 bytes to rupload.facebook.com
  4. wait until the container is FINISHED, then POST /{ig-user}/media_publish
"""
import argparse, json, os, random, sys, time
from datetime import datetime
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    uid, tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not uid or not tok:
        sys.exit("Missing IG_USER_ID / IG_ACCESS_TOKEN. Put them in a .env file (see README).")
    return uid, tok


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with open(ROOT / "post_log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def api(method, url, **kw):
    r = requests.request(method, url, timeout=120, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        raise RuntimeError(f"{r.status_code} {err.get('message', err) if isinstance(err, dict) else err}")
    return data


# ---------- audio ----------

def fetch_audio(cfg, uid, tok, query=None):
    a = cfg["audio"]
    params = {"audio_type": a["audio_type"], "user_id": uid, "access_token": tok}
    if query:
        params["search_query"] = query
    data = api("GET", f"{GRAPH}/{cfg['graph_version']}/ig_audio", params=params)
    items = data.get("audio") or data.get("data") or []
    out = []
    for it in items:
        aid = it.get("audio_id") or it.get("id")
        if aid:
            title = it.get("title") or it.get("song_name") or it.get("name") or ""
            artist = it.get("display_artist") or it.get("ig_username") or it.get("artist") or ""
            out.append({"id": str(aid), "title": title, "artist": artist})
    return out


def choose_audio(cfg, uid, tok, history):
    a = cfg["audio"]
    recent = set(history[-a["avoid_last"]:]) if a["avoid_last"] else set()
    if a["pinned_audio_ids"]:
        pool = [x for x in a["pinned_audio_ids"] if str(x) not in recent] or a["pinned_audio_ids"]
        return {"id": str(random.choice(pool)), "title": "(pinned)", "artist": ""}
    query = random.choice(a["search_queries"]) if a["search_queries"] else None
    options = fetch_audio(cfg, uid, tok, query)[: a["pick_from_top"]]
    if not options:
        return None
    fresh = [o for o in options if o["id"] not in recent] or options
    return random.choice(fresh)


# ---------- publishing ----------

def public_link(release, filename):
    """Public download link for a release file in this (public) GitHub repo.
    Meta only attaches audio to reels created from a video_url, so we hand it this link.
    GitHub redirects to a short-lived direct link; we resolve it so Meta gets the file directly."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("not running on GitHub Actions")
    url = f"https://github.com/{repo}/releases/download/{release}/{filename}"
    r = requests.head(url, allow_redirects=False, timeout=60)
    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
        return r.headers["Location"]
    if r.status_code == 200:
        return url
    raise RuntimeError(f"release file is not publicly reachable ({r.status_code}) - is the repo public?")


def create_container(cfg, uid, tok, item, audio, video_url=None):
    params = {
        "media_type": "REELS",
        "caption": item["caption"],
        "share_to_feed": "true",
        "access_token": tok,
    }
    if video_url:
        params["video_url"] = video_url
    else:
        params["upload_type"] = "resumable"
    if audio:
        params["audio_configuration"] = json.dumps({
            "audio_id": audio["id"],
            "audio_volume": cfg["audio"]["audio_volume"],
            "video_volume": cfg["audio"]["video_volume"],
        })
    return api("POST", f"{GRAPH}/{cfg['graph_version']}/{uid}/media", data=params)


def upload_video(cfg, tok, container_id, path, upload_uri=None):
    size = path.stat().st_size
    url = upload_uri or f"{RUPLOAD}/{cfg['graph_version']}/{container_id}"
    with open(path, "rb") as f:
        api("POST", url, headers={
            "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size),
        }, data=f)


def wait_until_ready(cfg, tok, container_id, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        d = api("GET", f"{GRAPH}/{cfg['graph_version']}/{container_id}",
                params={"fields": "status_code,status", "access_token": tok})
        code = d.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {d.get('status')}")
        time.sleep(10)
    raise RuntimeError("Timed out waiting for Instagram to process the video")


def publish(cfg, uid, tok, container_id):
    return api("POST", f"{GRAPH}/{cfg['graph_version']}/{uid}/media_publish",
               data={"creation_id": container_id, "access_token": tok})


def post_one(cfg, uid, tok, item, audio, release="reels"):
    url = None
    if audio:
        try:
            url = public_link(release, item["file"])
        except Exception as e:
            log(f"No public link ({e}); uploading directly - audio may not attach")
    c = create_container(cfg, uid, tok, item, audio, url)
    cid = c["id"]
    if not url:
        upload_video(cfg, tok, cid, ROOT / cfg["output_dir"] / item["file"], c.get("uri"))
    wait_until_ready(cfg, tok, cid)
    return publish(cfg, uid, tok, cid)["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-audio", nargs="*", metavar="WORDS")
    ap.add_argument("--next-file", action="store_true", help="print the next reel's file name and exit")
    ap.add_argument("--one-off", metavar="MP4", help="post this file once, outside the queue")
    ap.add_argument("--quote", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--release", default="reels")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.next_file:
        nxt = next((x for x in load_json(ROOT / "queue.json", []) if not x["posted"]), None)
        print(nxt["file"] if nxt else "")
        return
    # Warm-up week: skip some daily slots (3 posts/day instead of 5) until the date in config.
    w = cfg.get("warmup") or {}
    if w.get("until") and os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        now = datetime.utcnow()
        if now.strftime("%Y-%m-%d") < w["until"] and now.hour in w.get("skip_slots_utc_hours", []):
            print(f"Warm-up: skipping this slot until {w['until']}.")
            return

    uid, tok = load_env()

    if args.list_audio is not None:
        q = " ".join(args.list_audio) or None
        for o in fetch_audio(cfg, uid, tok, q):
            print(f"{o['id']:>22}  {o['title']}  -  {o['artist']}")
        return

    if args.one_off:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mr", ROOT / "make_reels.py")
        mr = importlib.util.module_from_spec(spec); spec.loader.exec_module(mr)
        item = {"file": args.one_off, "author": args.author or "-",
                "caption": mr.build_caption(cfg, args.quote, args.author)}
        state_path = ROOT / "state.json"
        state = load_json(state_path, {"audio_history": []})
        audio = choose_audio(cfg, uid, tok, state["audio_history"]) if cfg["audio"]["enabled"] else None
        try:
            media_id = post_one(cfg, uid, tok, item, audio, args.release)
        except Exception as e:
            if not audio:
                raise
            log(f"One-off with audio failed ({e}); retrying without audio")
            audio = None
            media_id = post_one(cfg, uid, tok, item, None, args.release)
        if audio:
            state["audio_history"] = (state["audio_history"] + [audio["id"]])[-50:]
            save_json(state_path, state)
        log(f"POSTED one-off {args.one_off} | audio: {audio['id'] if audio else 'none'} -> media {media_id}")
        return

    queue_path = ROOT / "queue.json"
    queue = load_json(queue_path, [])
    item = next((x for x in queue if not x["posted"]), None)
    if not item:
        log("Queue is empty - run make_reels.py to render more.")
        return

    state_path = ROOT / "state.json"
    state = load_json(state_path, {"audio_history": []})

    audio = None
    if cfg["audio"]["enabled"]:
        try:
            audio = choose_audio(cfg, uid, tok, state["audio_history"])
        except Exception as e:
            log(f"Could not fetch audio: {e}")

    label = f"{item['file']} | {item['author']} | audio: " + (f"{audio['title']} {audio['artist']} ({audio['id']})" if audio else "none")
    if args.dry_run:
        print("DRY RUN ->", label)
        print(item["caption"])
        return

    try:
        media_id = post_one(cfg, uid, tok, item, audio)
    except Exception as e:
        if audio and cfg["audio"]["post_without_audio_if_it_fails"]:
            log(f"Post with audio failed ({e}); retrying without audio")
            audio = None
            label = label.split(" | audio:")[0] + " | audio: none (fallback)"
            media_id = post_one(cfg, uid, tok, item, None)
        else:
            log(f"FAILED {label}: {e}")
            raise

    item.update(posted=True, media_id=media_id, posted_at=datetime.now().isoformat(timespec="seconds"),
                audio_id=audio["id"] if audio else None)
    save_json(queue_path, queue)
    if audio:
        state["audio_history"] = (state["audio_history"] + [audio["id"]])[-50:]
        save_json(state_path, state)
    left = sum(1 for x in queue if not x["posted"])
    log(f"POSTED {label} -> media {media_id}. {left} left in queue.")
    if left < 10:
        log("Heads up: fewer than 10 reels left. Run make_reels.py to top up.")


if __name__ == "__main__":
    main()
