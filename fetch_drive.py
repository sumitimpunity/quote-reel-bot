"""
fetch_drive.py - downloads every video from a PUBLIC Google Drive folder into videos/.

    python fetch_drive.py "https://drive.google.com/drive/folders/<FOLDER_ID>?usp=sharing"

The folder must be shared as "Anyone with the link". Files already in videos/ are skipped,
so re-running after adding new clips only fetches the new ones.
"""
import re, sys, html
from pathlib import Path
import requests
import gdown

ROOT = Path(__file__).resolve().parent
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")


def folder_id(url):
    m = re.search(r"folders/([A-Za-z0-9_-]+)", url) or re.search(r"id=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else url.strip()


def list_folder(fid):
    """Lists files via Drive's embedded folder view (no API key needed, no 50-file limit)."""
    r = requests.get(f"https://drive.google.com/embeddedfolderview?id={fid}#list", timeout=60)
    r.raise_for_status()
    entries = re.findall(
        r'id="entry-([A-Za-z0-9_-]+)".*?class="flip-entry-title">(.*?)</div>', r.text, re.S)
    return [(i, html.unescape(n).strip()) for i, n in entries]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = ROOT / "videos"
    out.mkdir(exist_ok=True)
    fid = folder_id(sys.argv[1])
    files = list_folder(fid)
    if not files:
        print("Folder listing came back empty - falling back to gdown's folder download (max 50 files).")
        gdown.download_folder(id=fid, output=str(out), quiet=False, remaining_ok=True)
        n = sum(1 for p in out.iterdir() if p.suffix.lower() in VIDEO_EXT)
        print(f"{n} videos ready in videos/")
        sys.exit(0 if n else 1)
    vids = [(i, n) for i, n in files if n.lower().endswith(VIDEO_EXT)]
    print(f"Found {len(files)} items, {len(vids)} videos.")
    if not vids:
        sys.exit("No videos found. Is the folder shared as 'Anyone with the link'?")
    ok = 0
    for k, (fid, name) in enumerate(vids, 1):
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
        dest = out / safe
        if dest.exists() and dest.stat().st_size > 0:
            ok += 1
            continue
        print(f"[{k}/{len(vids)}] {name}")
        try:
            gdown.download(id=fid, output=str(dest), quiet=True)
            ok += dest.exists()
        except Exception as e:
            print(f"   ! failed: {e}")
    print(f"{ok}/{len(vids)} videos ready in videos/")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
