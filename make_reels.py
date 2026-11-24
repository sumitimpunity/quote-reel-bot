"""
make_reels.py - turns your stock clips + quotes.csv into finished 9:16 quote reels.

    python make_reels.py              # render every clip once (150 clips = 30 days at 5/day)
    python make_reels.py --count 10   # render just 10 (good for a first test)
    python make_reels.py --preview    # render 1 reel to output/preview.mp4 and stop

Each reel: clip cropped to 1080x1920, slightly darkened, quote fades in, author below,
your handle at the bottom. Clip length is random between min_seconds and max_seconds.
Rendered reels are added to queue.json, which post_next.py works through in order.
"""
import argparse, csv, json, random, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def font(name, size, variation=None):
    f = ImageFont.truetype(str(ROOT / "fonts" / name), size)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:
            pass
    return f


def wrap_to_width(text, fnt, max_w, draw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_text_png(quote, author, handle, style, out_path):
    """Transparent 1080x1920 PNG with the quote, author and handle, plus a soft shadow."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    max_w = W - 2 * style["side_margin"]

    # Shrink the quote font until the block fits comfortably.
    size = style["quote_size"]
    while True:
        qf = font(style["quote_font"], size, style.get("quote_weight"))
        lines = wrap_to_width(quote, qf, max_w, d)
        # Balance the lines: narrow the box while the line count stays the same,
        # so the last line isn't a single dangling word.
        bw = max_w
        while bw > max_w * 0.6:
            trial = wrap_to_width(quote, qf, bw - 20, d)
            if len(trial) != len(lines):
                break
            bw -= 20
            lines = trial
        line_h = int(size * 1.35)
        block_h = line_h * len(lines)
        if block_h <= H * 0.42 or size <= 40:
            break
        size -= 4

    af = font(style["author_font"], style["author_size"])
    hf = font(style["author_font"], style["handle_size"])
    author_txt = "— " + author.upper()
    gap = int(size * 0.9)
    total = block_h + gap + style["author_size"]
    y = int(H * style["vertical_center"]) - total // 2

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for ln in lines:
        lw = ld.textlength(ln, font=qf)
        ld.text(((W - lw) / 2, y), ln, font=qf, fill=tuple(style["text_color"]))
        y += line_h
    y += gap
    aw = ld.textlength(author_txt, font=af)
    ld.text(((W - aw) / 2, y), author_txt, font=af, fill=tuple(style["author_color"]))
    if handle:
        hw = ld.textlength(handle, font=hf)
        ld.text(((W - hw) / 2, style["handle_top"]), handle, font=hf, fill=tuple(style["handle_color"]))

    # Shadow = blurred black copy of the text alpha.
    alpha = layer.split()[3]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: int(a * 0.75)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(shadow)
    img.alpha_composite(layer)
    img.save(out_path)


def probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def render_reel(clip, png, dur, style, out_path):
    src_len = probe_duration(clip)
    # Start somewhere random inside the clip if it is long enough; otherwise loop it.
    start = random.uniform(0, max(0.0, src_len - dur - 0.1)) if src_len > dur + 0.5 else 0.0
    loop = ["-stream_loop", "-1"] if src_len and src_len < dur + 0.1 else []
    fade_in = style["text_fade_in_at"]
    vf = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,"
        f"eq=brightness={style['dim_brightness']}:saturation={style['saturation']}[bg];"
        f"[1:v]format=rgba,fade=in:st={fade_in}:d=0.8:alpha=1[tx];"
        f"[bg][tx]overlay=0:0:format=auto,fade=out:st={dur - 0.4:.2f}:d=0.4,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *loop, "-ss", f"{start:.2f}", "-i", str(clip),
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
        "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def build_caption(cfg, quote, author):
    tmpl = random.choice(cfg["caption_templates"])
    return tmpl.format(quote=quote, author=author, handle=cfg["handle"]).strip() + "\n\n" + cfg["hashtags"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=0, help="how many reels to render (default: one per clip)")
    ap.add_argument("--preview", action="store_true", help="render one reel to output/preview.mp4 and stop")
    args = ap.parse_args()

    cfg = load_config()
    style = cfg["style"]
    videos_dir = ROOT / cfg["videos_dir"]
    out_dir = ROOT / cfg["output_dir"]
    out_dir.mkdir(exist_ok=True)
    queue_path = ROOT / "queue.json"
    queue = load_json(queue_path, [])

    clips = sorted(p for p in videos_dir.iterdir() if p.suffix.lower() in VIDEO_EXT)
    if not clips:
        sys.exit(f"No videos found in {videos_dir}. Put your stock clips there first.")
    with open(ROOT / cfg["quotes_file"], encoding="utf-8") as f:
        quotes = [r for r in csv.DictReader(f) if r["quote"].strip()]

    # Prefer quotes and clips that have been used least, so nothing repeats until it has to.
    used_q = {}
    used_c = {}
    for item in queue:
        used_q[item["quote"]] = used_q.get(item["quote"], 0) + 1
        used_c[item["clip"]] = used_c.get(item["clip"], 0) + 1
    random.shuffle(clips)
    random.shuffle(quotes)
    clips.sort(key=lambda c: used_c.get(c.name, 0))
    quotes.sort(key=lambda q: used_q.get(q["quote"], 0))

    n = 1 if args.preview else (args.count or len(clips))
    next_no = max([item["no"] for item in queue], default=0) + 1

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            clip = clips[i % len(clips)]
            q = quotes[i % len(quotes)]
            dur = round(random.uniform(cfg["min_seconds"], cfg["max_seconds"]), 1)
            png = Path(tmp) / f"text_{i}.png"
            render_text_png(q["quote"], q["author"], cfg["handle"], style, png)
            name = "preview.mp4" if args.preview else f"reel_{next_no:04d}.mp4"
            out = out_dir / name
            print(f"[{i + 1}/{n}] {name}  <- {clip.name}  ({dur}s)  \"{q['quote'][:50]}...\"")
            try:
                render_reel(clip, png, dur, style, out)
            except subprocess.CalledProcessError:
                print(f"   ! ffmpeg failed on {clip.name}, skipping")
                continue
            if args.preview:
                print(f"Preview saved to {out}")
                return
            queue.append({
                "no": next_no, "file": name, "clip": clip.name, "quote": q["quote"],
                "author": q["author"], "caption": build_caption(cfg, q["quote"], q["author"]),
                "posted": False,
            })
            save_json(queue_path, queue)  # save after every reel so a crash loses nothing
            next_no += 1

    pending = sum(1 for x in queue if not x["posted"])
    print(f"\nDone. {pending} reels waiting in the queue "
          f"(~{pending / max(1, len(cfg['post_times'])):.0f} days of posting).")


if __name__ == "__main__":
    main()
