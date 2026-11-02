#!/usr/bin/env python3
"""Build the panel's game pictures and sounds from YOUR OWN copy of Counter-Strike 1.5.

These files are Valve's, so they are not in the repository; the panel works without them
(no map pictures, no menu sounds). This script makes them from a game folder on your disk:

  previews  static/maps/<map>.jpg (640x360) and static/maps/thumb/<map>.jpg (192x108) —
            a rendered view of every map of your server (needs numpy and Pillow);
  sfx       static/hl/sfx/launch_*.wav - the menu sounds of the old (WON) menu;
  logo      static/hl/logo.webm - the spinning COUNTER-STRIKE logo of that menu (cstrike/media/logo.avi,
            the dedicated server has it), shown on the login screen (needs ffmpeg);
  emblem    static/hl/emblem.png - the round Counter-Strike logo from the corner of the old menu's
            background (cstrike/gfx/shell/splash.bmp): next to every page title and on the browser tab
            (needs Pillow; without it the panel shows its own crosshair);
  music     static/music/hl-NN.mp3 - the Half-Life soundtrack, if your game is the Steam version
            (valve/media/Half-Life01.mp3 ...); listed in static/music/tracks.local.json.

Everything is looked up in the mod folder first (--mod, cstrike by default), then in valve/.

Usage (on the server or on your PC, then copy the static/ files over):

    pip install numpy pillow
    python3 tools/build_assets.py --game "/path/to/Half-Life"            # everything it can find
    python3 tools/build_assets.py --game ... --only previews --force     # redraw all map pictures
    python3 tools/build_assets.py --game ... --maps /srv/hlds/cstrike/maps # maps from another folder

--game is the folder that contains valve/ and cstrike/ (a game client or a dedicated server install).
Maps are taken from MAPS_DIRS in .env (the server's maps), --maps, <game>/cstrike/maps and
<game>/valve/pak0.pak; textures from the .wad files in <game>/cstrike and <game>/valve. Without
.env every map that is found gets a picture.
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
sys.path.insert(0, str(ROOT))

SFX = ("launch_deny1", "launch_deny2", "launch_dnmenu1", "launch_glow1", "launch_select1", "launch_select2",
       "launch_upmenu1")


def pak_maps(path):
    """{map: bytes} from a Quake/Half-Life PAK file."""
    out = {}
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if head[:4] != b"PACK":
                return out
            ofs, size = struct.unpack("<ii", head[4:])
            f.seek(ofs)
            table = f.read(size)
            for i in range(size // 64):
                name, pos, ln = struct.unpack_from("<56sii", table, i * 64)
                name = name.split(b"\0")[0].decode("latin1").lower()
                if name.startswith("maps/") and name.endswith(".bsp"):
                    f.seek(pos)
                    out[name[5:-4]] = f.read(ln)
    except OSError:
        pass
    return out


def find_maps(dirs, game):
    """{map: path or bytes}: folders first (the server's own maps win), then pak0.pak."""
    found = {}
    for d in dirs:
        try:
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".bsp"):
                    found.setdefault(f[:-4].lower(), os.path.join(d, f))
        except OSError:
            continue
    if game:
        for name, data in pak_maps(os.path.join(game, "valve", "pak0.pak")).items():
            found.setdefault(name, data)
    return found


def cameras():
    """Hand-picked views (tools/map_cameras.txt): {map: (x, y, z, yaw, pitch)}."""
    out = {}
    try:
        for line in open(Path(__file__).with_name("map_cameras.txt"), encoding="utf-8"):
            p = line.split("#")[0].split()
            if len(p) == 6:
                out[p[0].lower()] = tuple(float(x) for x in p[1:])
    except OSError:
        pass
    return out


def media(game, mod, name):
    """<game>/<mod>/media/<name>, а если там нет — <game>/valve/media/<name>."""
    for d in (mod, "valve"):
        f = Path(game, d, "media", name)
        if f.exists():
            return f
    return Path(game, mod, "media", name)


def build_previews(maps, game, force, only_names, mod="cstrike"):
    try:
        import numpy as np
        from PIL import Image
        import bsp_render as R
    except ImportError as e:
        print("previews: skipped (%s) - install them: pip install numpy pillow" % e)
        return
    # текстуры: сначала .wad мода (cstrike.wad, de_aztec.wad …), потом valve (halflife.wad, liquids.wad)
    wad_dirs = [os.path.join(game, mod), os.path.join(game, "valve")] if game else []
    wads = R.Wads([str(p) for d in wad_dirs for p in sorted(Path(d).glob("*.wad"))])
    if not wads.index:
        print("previews: no .wad textures in %s - the pictures will be grey" % (" ".join(wad_dirs) or "(no --game)"))
    out, thumbs = STATIC / "maps", STATIC / "maps" / "thumb"
    thumbs.mkdir(parents=True, exist_ok=True)
    cams = cameras()
    names = sorted(m for m in maps if not only_names or m in only_names)
    for name in names:
        dst = out / (name + ".jpg")
        if dst.exists() and not force:
            continue
        src = maps[name]
        try:
            data = src if isinstance(src, bytes) else open(src, "rb").read()
            bsp = R.BSP(data, wads)
            if name in cams:
                x, y, z, yaw, pitch = cams[name]
                eye = np.array([x, y, z])
            else:
                eye, yaw, pitch = R.choose_view(bsp)
            img, _, _ = R.render(bsp, eye, yaw, pitch, 1280, 720)
            im = Image.fromarray(img).resize((640, 360), Image.LANCZOS)
            im.save(dst, quality=86, optimize=True, progressive=True)
            im.resize((192, 108), Image.LANCZOS).save(thumbs / (name + ".jpg"), quality=82, optimize=True)
            print("preview  %-16s %s" % (name, "(missing textures: %s)" % ", ".join(bsp.missing_tex[:4])
                                           if bsp.missing_tex else "ok"), flush=True)
        except Exception as e:      # кривая карта не должна останавливать остальные
            print("preview  %-16s FAILED: %s" % (name, e), flush=True)


def build_sfx(game, mod):
    dst = STATIC / "hl" / "sfx"
    got = [(s, media(game, mod, s + ".wav")) for s in SFX if media(game, mod, s + ".wav").exists()]
    if not got:
        print("sfx: no launch_*.wav in %s/media or valve/media (only the old WON menu has them)" % mod)
        return
    dst.mkdir(parents=True, exist_ok=True)
    for s, f in got:
        shutil.copy2(f, dst / (s + ".wav"))
    print("sfx: %d menu sounds -> %s" % (len(got), dst))


def build_logo(game, force, mod):
    src = media(game, mod, "logo.avi")
    dst = STATIC / "hl" / "logo.webm"
    if not src.exists():
        print("logo: no %s" % src)
        return
    if src.stat().st_size < 10000:
        # Counter-Strike 1.5 кладёт 16x16-заглушку: в его меню вращающегося логотипа нет
        print("logo: %s is an empty placeholder - no logo on the login screen" % src)
        return
    if dst.exists() and not force:
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("logo: ffmpeg not found - install it to convert logo.avi")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-an", "-c:v", "libvpx-vp9",
                        "-b:v", "0", "-crf", "36", "-row-mt", "1", str(dst)], capture_output=True, text=True)
    print("logo: %s" % ("-> %s" % dst if r.returncode == 0 else "ffmpeg failed: " + r.stderr[-300:]))


def build_emblem(game, force, mod):
    src = Path(game, mod, "gfx", "shell", "splash.bmp")
    dst = STATIC / "hl" / "emblem.png"
    if not src.exists():
        print("emblem: no %s (only the old WON menu has it)" % src)
        return
    if dst.exists() and not force:
        return
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        print("emblem: skipped (%s) - install it: pip install pillow" % e)
        return
    im = Image.open(src).convert("RGB")
    w, h = im.size
    # светлый серый круг эмблемы — в правом нижнем углу заставки; ищем его по светлым серым точкам
    px = im.load()
    pts = [(x, y) for y in range(max(0, h - 120), h) for x in range(max(0, w - 100), w)
           if min(px[x, y]) > 150 and max(px[x, y]) - min(px[x, y]) < 30]
    if len(pts) < 500:
        print("emblem: no round logo in the corner of %s" % src)
        return
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2
    r = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 2.5       # + тёмная кайма вокруг круга
    part = im.crop((round(cx - r), round(cy - r), round(cx + r), round(cy + r))).convert("RGBA")
    n = part.size[0]
    mask = Image.new("L", (n * 8, n * 8), 0)        # круг рисуется крупно и уменьшается — края гладкие
    ImageDraw.Draw(mask).ellipse((0, 0, n * 8 - 1, n * 8 - 1), fill=255)
    part.putalpha(mask.resize((n, n), Image.LANCZOS))
    dst.parent.mkdir(parents=True, exist_ok=True)
    part.save(dst, optimize=True)
    print("emblem: %dx%d -> %s" % (n, n, dst))


def build_music(game):
    src = Path(game, "valve", "media")
    tracks = sorted(src.glob("Half-Life[0-9][0-9].mp3"))
    if not tracks:
        print("music: no valve/media/Half-Life??.mp3 (the WON version plays music from the CD)")
        return
    dst = STATIC / "music"
    dst.mkdir(parents=True, exist_ok=True)
    listed = []
    for t in tracks:
        nr = t.stem[-2:]
        name = "hl-%s.mp3" % nr
        shutil.copy2(t, dst / name)
        listed.append({"file": name, "title": "Half-Life %s" % nr, "author": "Kelly Bailey (Valve)", "license": "© Valve"})
    (dst / "tracks.local.json").write_text(json.dumps(listed, ensure_ascii=False, indent=1), encoding="utf-8")
    print("music: %d tracks -> %s" % (len(listed), dst))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", help="folder with valve/ and cstrike/ inside (game client or dedicated server)")
    ap.add_argument("--mod", default="cstrike", help="mod folder inside --game (default: cstrike)")
    ap.add_argument("--maps", action="append", default=[], help="extra folder with .bsp maps (can repeat)")
    ap.add_argument("--only", default="previews,sfx,logo,emblem,music",
                    help="comma list: previews,sfx,logo,emblem,music")
    ap.add_argument("--force", action="store_true", help="rebuild files that already exist")
    args = ap.parse_args()
    parts = {p.strip() for p in args.only.split(",") if p.strip()}
    game = args.game or ""
    if game and not Path(game, "valve").is_dir():
        sys.exit("%s has no valve/ folder - pass the Half-Life folder itself" % game)

    server_maps, dirs = set(), list(args.maps)
    try:
        import config
        cfg = config.Config()
        if cfg.path.exists():
            dirs += cfg.maps_dirs
            import cfg as cfg_mod
            server_maps = set(cfg_mod.MapPool(cfg.mappool, cfg.mapcycle, cfg.maps_dirs, None).available())
    except Exception as e:      # без .env - просто все найденные карты
        print("(.env not used: %s)" % e)
    if game:
        dirs.append(os.path.join(game, args.mod, "maps"))

    if "previews" in parts:
        maps = find_maps(dirs, game)
        if not maps:
            print("previews: no maps found (set MAPS_DIRS in .env, or --maps, or --game)")
        else:
            print("previews: %d maps%s" % (len(server_maps) or len(maps), " (the server's)" if server_maps else ""))
            build_previews(maps, game, args.force, server_maps, args.mod)
    if not game:
        if parts - {"previews"}:
            print("sfx/logo/emblem/music need --game")
        return
    if "sfx" in parts:
        build_sfx(game, args.mod)
    if "logo" in parts:
        build_logo(game, args.force, args.mod)
    if "emblem" in parts:
        build_emblem(game, args.force, args.mod)
    if "music" in parts:
        build_music(game)
    print("Done. Reload the panel page (F5).")


if __name__ == "__main__":
    main()
