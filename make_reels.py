"""
make_reels.py - turns your stock clips + quotes.csv into finished 9:16 aesthetic quote reels.

    python make_reels.py              # render every clip once
    python make_reels.py --count 10   # render just 10
    python make_reels.py --preview 6  # render 6 samples to output/preview_N.mp4 (queue untouched)

Look: small, simple text over the clip in its natural colours, a light film grade (warmth, grain,
soft vignette), the quote fading in, a tiny author line and a tiny watermark. Each reel randomly
uses one of the text styles in config.json "looks", so the feed doesn't feel repetitive.
"""
import argparse, csv, json, random, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def font(name, size, weight=400):
    """Loads a font from fonts/; for variable fonts, sets the weight axis and leaves others at default."""
    path = ROOT / "fonts" / name
    if not path.exists():
        fallback = ROOT / "fonts" / "Poppins-Regular.ttf"
        print(f"   (font {name} missing, using Poppins)")
        path = fallback
    f = ImageFont.truetype(str(path), size)
    try:
        axes = f.get_variation_axes()
        vals = []
        for a in axes:
            nm = str(a.get("name", b"")).lower()
            if "weight" in nm or "wght" in nm:
                vals.append(max(a["minimum"], min(a["maximum"], weight)))
            elif "optical" in nm or "opsz" in nm:
                vals.append(max(a["minimum"], min(a["maximum"], 32)))
            else:
                vals.append(a.get("default", a["minimum"]))
        f.set_variation_by_axes(vals)
    except Exception:
        pass
    return f


def wrap(text, fnt, max_w, draw):
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
    # Balance: narrow the box while the line count stays the same (no lonely last word).
    bw = max_w
    while bw > max_w * 0.55:
        trial = wrap_plain(text, fnt, bw - 20, draw)
        if len(trial) != len(lines):
            break
        bw -= 20
        lines = trial
    return lines


def wrap_plain(text, fnt, max_w, draw):
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


def apply_case(s, case):
    return s.lower() if case == "lower" else s


def render_text_png(quote, author, handle, look, common, out_path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    q = apply_case(quote, look["case"])
    qf = font(look["font"], look["size"], look.get("weight", 400))
    lines = wrap(q, qf, look["max_width"], d)
    line_h = int(look["size"] * look.get("line_height", 1.35))
    block_h = line_h * len(lines)

    show_author = look.get("show_author", True)
    af = font(common["small_font"], common["author_size"], 400)
    a_txt = apply_case("— " + author, look["case"])
    gap = int(look["size"] * 1.1)
    total = block_h + (gap + common["author_size"] if show_author else 0)
    y = int(H * look.get("vertical_center", 0.46)) - total // 2

    color = tuple(look["color"])
    for ln in lines:
        lw = d.textlength(ln, font=qf)
        d.text(((W - lw) / 2, y), ln, font=qf, fill=color)
        y += line_h
    if show_author:
        y += gap - (line_h - look["size"])
        aw = d.textlength(a_txt, font=af)
        d.text(((W - aw) / 2, y), a_txt, font=af, fill=tuple(common["author_color"]))
    if handle:
        hf = font(common["small_font"], common["handle_size"], 400)
        hw = d.textlength(handle, font=hf)
        d.text(((W - hw) / 2, H - common["handle_bottom"]), handle, font=hf, fill=tuple(common["handle_color"]))

    # Soft, wide shadow so small white text stays readable on bright clips without a dark overlay.
    alpha = layer.split()[3]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(alpha.point(lambda a: int(a * common["shadow_strength"])))
    shadow = shadow.filter(ImageFilter.GaussianBlur(common["shadow_blur"]))
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


def render_reel(clip, png, dur, grade, out_path):
    src_len = probe_duration(clip)
    start = random.uniform(0, max(0.0, src_len - dur - 0.1)) if src_len > dur + 0.5 else 0.0
    loop = ["-stream_loop", "-1"] if src_len and src_len < dur + 0.1 else []
    look_filters = (
        f"eq=brightness={grade['brightness']}:contrast={grade['contrast']}:saturation={grade['saturation']},"
        f"colorbalance=rs={grade['warmth']}:gs={grade['warmth'] / 3:.3f}:bs={-grade['warmth']},"
        f"vignette=angle={grade['vignette']},"
        f"noise=alls={grade['grain']}:allf=t"
    )
    vf = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,{look_filters}[bg];"
        f"[1:v]format=rgba,fade=in:st={grade['text_fade_in_at']}:d=1.2:alpha=1[tx];"
        f"[bg][tx]overlay=0:0:format=auto,fade=out:st={dur - 0.4:.2f}:d=0.4,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *loop, "-ss", f"{start:.2f}", "-i", str(clip),
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
        "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def build_caption(cfg, quote, author):
    tmpl = random.choice(cfg["caption_templates"])
    return tmpl.format(quote=quote, author=author, handle=cfg["handle"]).strip() + "\n\n" + cfg["hashtags"]


def pick_look(looks):
    return random.choices(looks, weights=[lk.get("weight_share", 1) for lk in looks])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=0, help="how many reels to render (default: one per clip)")
    ap.add_argument("--preview", type=int, nargs="?", const=1, default=0,
                    help="render N samples to output/preview_N.mp4 without touching the queue")
    args = ap.parse_args()

    cfg = load_json(ROOT / "config.json", {})
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

    used_q, used_c = {}, {}
    for item in queue:
        used_q[item["quote"]] = used_q.get(item["quote"], 0) + 1
        used_c[item["clip"]] = used_c.get(item["clip"], 0) + 1
    random.shuffle(clips)
    random.shuffle(quotes)
    clips.sort(key=lambda c: used_c.get(c.name, 0))
    quotes.sort(key=lambda q: used_q.get(q["quote"], 0))

    n = args.preview or args.count or len(clips)
    next_no = max([item["no"] for item in queue], default=0) + 1

    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            clip = clips[i % len(clips)]
            q = quotes[i % len(quotes)]
            look = pick_look(style["looks"])
            dur = round(random.uniform(cfg["min_seconds"], cfg["max_seconds"]), 1)
            png = Path(tmp) / f"text_{i}.png"
            render_text_png(q["quote"], q["author"], cfg["handle"], look, style["common"], png)
            name = f"preview_{i + 1}.mp4" if args.preview else f"reel_{next_no:04d}.mp4"
            out = out_dir / name
            print(f"[{i + 1}/{n}] {name}  <- {clip.name}  ({dur}s, {look['name']})  \"{q['quote'][:50]}...\"")
            try:
                render_reel(clip, png, dur, style["grade"], out)
            except subprocess.CalledProcessError:
                print(f"   ! ffmpeg failed on {clip.name}, skipping")
                continue
            if args.preview:
                continue
            queue.append({
                "no": next_no, "file": name, "clip": clip.name, "quote": q["quote"],
                "author": q["author"], "look": look["name"],
                "caption": build_caption(cfg, q["quote"], q["author"]), "posted": False,
            })
            save_json(queue_path, queue)
            next_no += 1

    if not args.preview:
        pending = sum(1 for x in queue if not x["posted"])
        print(f"\nDone. {pending} reels waiting in the queue.")


if __name__ == "__main__":
    main()
