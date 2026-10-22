#!/usr/bin/env python3
"""Software renderer for Half-Life maps (BSP v30): a textured, lit view from inside the map.

Used by tools/build_assets.py to draw map pictures for the panel. Needs numpy and Pillow.
Textures come from the map itself and from the game's WAD files (halflife.wad, liquids.wad, …).
The camera stands at a spawn point (info_player_deathmatch) at eye height; of several spawn
points and turns the view with the most open space wins — or a hand-picked camera is used.
"""
import math
import re
import struct

import numpy as np

SKIP_TEX = {"aaatrigger", "clip", "origin", "null", "hint", "skip", "bevel", "black_hidden"}
SKIP_CLASSES = {"func_ladder", "func_monsterclip", "func_friction", "env_bubbles", "func_traincontrols",
                "func_tankcontrols", "func_mortar_field", "func_buyzone", "func_bomb_target",
                "func_hostage_rescue", "func_vip_safetyzone", "func_escapezone"}


def parse_ents(text):
    ents = []
    for block in re.findall(r"\{([^{}]*)\}", text):
        ents.append(dict(re.findall(r'"([^"]*)"\s*"([^"]*)"', block)))
    return ents


def read_miptex(buf, base):
    name = buf[base:base + 16].split(b"\0")[0].decode("latin1").lower()
    w, h = struct.unpack_from("<II", buf, base + 16)
    offs = struct.unpack_from("<4I", buf, base + 24)
    if offs[0] == 0:
        return name, w, h, None
    pix = np.frombuffer(buf, np.uint8, w * h, base + offs[0]).reshape(h, w)
    pal = np.frombuffer(buf, np.uint8, 768, base + offs[3] + (w // 8) * (h // 8) + 2).reshape(256, 3)
    return name, w, h, (pix, pal)


class Wads:
    """Textures of the game's WAD3 files, read on demand."""

    def __init__(self, paths):
        self.index = {}
        self.data = []
        for path in paths:
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            if data[:4] != b"WAD3":
                continue
            n, ofs = struct.unpack_from("<ii", data, 4)
            k = len(self.data)
            self.data.append(data)
            for i in range(n):
                filepos, _, _, typ, _, _, name = struct.unpack_from("<iiibbh16s", data, ofs + i * 32)
                name = name.split(b"\0")[0].decode("latin1").lower()
                if typ == 0x43 and name not in self.index:
                    self.index[name] = (k, filepos)

    def get(self, name):
        hit = self.index.get(name)
        if not hit:
            return None
        return read_miptex(self.data[hit[0]], hit[1])[3]


class BSP:
    def __init__(self, d, wads):
        assert struct.unpack_from("<i", d, 0)[0] == 30, "not a BSP v30 map"
        lumps = [struct.unpack_from("<ii", d, 4 + 8 * i) for i in range(15)]

        def lump(i):
            o, ln = lumps[i]
            return d[o:o + ln]

        self.ents = parse_ents(lump(0).decode("latin1", "replace"))
        pl = np.frombuffer(lump(1), np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
        self.plane_n = pl["n"].astype(np.float64)
        self.plane_d = pl["d"].astype(np.float64)
        self.verts = np.frombuffer(lump(3), "<f4").reshape(-1, 3).astype(np.float64)
        ti = np.frombuffer(lump(6), np.dtype([("v", "<f4", (2, 4)), ("m", "<i4"), ("f", "<i4")]))
        self.ti_v = ti["v"].astype(np.float64)
        self.ti_m = ti["m"]
        self.faces = np.frombuffer(lump(7), np.dtype([("p", "<u2"), ("side", "<u2"), ("fe", "<i4"), ("ne", "<u2"),
                                                      ("ti", "<u2"), ("st", "u1", 4), ("lo", "<i4")]))
        self.light = np.frombuffer(lump(8), np.uint8)
        self.edges = np.frombuffer(lump(12), "<u2").reshape(-1, 2)
        self.surfedges = np.frombuffer(lump(13), "<i4")
        self.models = np.frombuffer(lump(14), np.dtype([("mins", "<f4", 3), ("maxs", "<f4", 3), ("org", "<f4", 3),
                                                        ("head", "<i4", 4), ("vl", "<i4"), ("ff", "<i4"),
                                                        ("nf", "<i4")]))
        tl = lump(2)
        n = struct.unpack_from("<i", tl, 0)[0]
        offs = struct.unpack_from("<%di" % n, tl, 4)
        self.texnames, self.textures = [], []
        for o in offs:
            if o < 0:
                self.texnames.append("")
                self.textures.append(None)
                continue
            name, w, h, tex = read_miptex(tl, o)
            self.texnames.append(name)
            self.textures.append(tex)
        missing = set()
        for i, t in enumerate(self.textures):
            if t is None and self.texnames[i]:
                self.textures[i] = wads.get(self.texnames[i])
                if self.textures[i] is None:
                    missing.add(self.texnames[i])
        self.missing_tex = sorted(missing)
        self.prepare()
        self.cen = np.array([it["c"] for it in self.items])
        self.rad = np.array([it["r"] for it in self.items])
        self.nrm = np.array([it["n"] for it in self.items])
        self.dst = np.array([it["dist"] for it in self.items])

    def face_polygon(self, fi):
        f = self.faces[fi]
        se = self.surfedges[f["fe"]:f["fe"] + f["ne"]]
        idx = np.where(se >= 0, self.edges[np.abs(se), 0], self.edges[np.abs(se), 1])
        return self.verts[idx]

    def prepare(self):
        """Faces to draw: the world and visible brush entities."""
        draw = [(0, np.zeros(3), "solid", 1.0)]
        for e in self.ents:
            m = e.get("model", "")
            if not m.startswith("*"):
                continue
            cls = e.get("classname", "")
            if cls.startswith("trigger_") or cls in SKIP_CLASSES:
                continue
            rmode = int(float(e.get("rendermode", "0") or 0))
            ramt = float(e.get("renderamt", "255") or 255)
            if rmode != 0 and ramt <= 0:
                continue
            org = np.array([float(x) for x in e.get("origin", "0 0 0").split()[:3]] or [0, 0, 0])
            mode = "blend" if rmode in (2, 3) else "add" if rmode == 5 else "solid"
            draw.append((int(m[1:]), org, mode, min(1.0, ramt / 255.0) if rmode else 1.0))
        self.items = []
        for mi, org, mode, alpha in draw:
            if mi >= len(self.models):
                continue
            mdl = self.models[mi]
            for fi in range(mdl["ff"], mdl["ff"] + mdl["nf"]):
                f = self.faces[fi]
                ti = f["ti"]
                tname = self.texnames[self.ti_m[ti]] if self.ti_m[ti] < len(self.texnames) else ""
                if tname in SKIP_TEX:
                    continue
                poly = self.face_polygon(fi) + org
                n = self.plane_n[f["p"]].copy()
                dist = self.plane_d[f["p"]]
                if f["side"]:
                    n, dist = -n, -dist
                dist = dist + n.dot(org)
                vecs = self.ti_v[ti]
                tex = self.textures[self.ti_m[ti]]
                sky = tname == "sky"
                lm = None
                local = poly - org
                st = local.dot(vecs[:, :3].T) + vecs[:, 3]
                mins = np.floor(st.min(0) / 16.0)
                maxs = np.ceil(st.max(0) / 16.0)
                lw, lh = int(maxs[0] - mins[0] + 1), int(maxs[1] - mins[1] + 1)
                if f["lo"] >= 0 and not sky and f["st"][0] != 255:
                    end = f["lo"] + lw * lh * 3
                    if end <= len(self.light):
                        lm = self.light[f["lo"]:end].reshape(lh, lw, 3).astype(np.float32)
                c = poly.mean(0)
                self.items.append(dict(c=c, r=float(np.sqrt(((poly - c) ** 2).sum(1)).max()), poly=poly, n=n,
                                       dist=dist, vecs=vecs, org=org, tex=tex, sky=sky, masked=tname.startswith("{"),
                                       lm=lm, lmins=mins, mode=mode, alpha=alpha, water=tname.startswith("!")))

    def spawns(self):
        out = []
        for e in self.ents:
            if e.get("classname") in ("info_player_deathmatch", "info_player_start"):
                try:
                    o = np.array([float(x) for x in e["origin"].split()])
                except (KeyError, ValueError):
                    continue
                yaw = 0.0
                if "angles" in e:
                    yaw = float(e["angles"].split()[1])
                elif "angle" in e:
                    yaw = float(e["angle"])
                out.append((o, yaw))
        return out


def sky_color(H, W):
    t = np.linspace(0, 1, H)[:, None, None]
    top = np.array([70, 100, 150], np.float32)
    hor = np.array([165, 175, 185], np.float32)
    return np.broadcast_to(top + (hor - top) * t, (H, W, 3)).copy()


def render(bsp, eye, yaw, pitch, W, H, fov=90.0, shade=True):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    fwd = np.array([cp * cy, cp * sy, -sp])
    right = np.array([sy, -cy, 0.0])
    up = np.array([sp * cy, sp * sy, cp])
    f = (W / 2.0) / math.tan(math.radians(fov) / 2.0)
    zbuf = np.full((H, W), np.inf, np.float64)
    img = sky_color(H, W) if shade else None
    skymask = np.zeros((H, W), bool)
    near = 1.0
    translucent = []

    def raster(it, write):
        n = it["n"]
        if n.dot(eye) - it["dist"] <= 0.01:
            return
        rel = it["poly"] - eye
        cam = np.stack([rel.dot(right), rel.dot(up), rel.dot(fwd)], 1)
        if (cam[:, 2] < near).any():                     # clip by the near plane
            out = []
            m = len(cam)
            for i in range(m):
                a, b = cam[i], cam[(i + 1) % m]
                ain, bin_ = a[2] >= near, b[2] >= near
                if ain:
                    out.append(a)
                if ain != bin_:
                    t = (near - a[2]) / (b[2] - a[2])
                    out.append(a + (b - a) * t)
            if len(out) < 3:
                return
            cam = np.array(out)
        sx = W / 2.0 + cam[:, 0] / cam[:, 2] * f
        syy = H / 2.0 - cam[:, 1] / cam[:, 2] * f
        x0, x1 = max(0, int(math.floor(sx.min()))), min(W, int(math.ceil(sx.max())) + 1)
        y0, y1 = max(0, int(math.floor(syy.min()))), min(H, int(math.ceil(syy.max())) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        PX, PY = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        m = len(sx)
        area = sum(sx[i] * syy[(i + 1) % m] - sx[(i + 1) % m] * syy[i] for i in range(m))
        sgn = 1.0 if area > 0 else -1.0
        inside = np.ones(PX.shape, bool)
        for i in range(m):
            j = (i + 1) % m
            ex, ey = sx[j] - sx[i], syy[j] - syy[i]
            inside &= (sgn * (ex * (PY - syy[i]) - ey * (PX - sx[i]))) >= -0.01 * (abs(ex) + abs(ey))
        if not inside.any():
            return
        dx = (PX - W / 2.0) / f
        dy = -(PY - H / 2.0) / f
        nd = n.dot(right) * dx + n.dot(up) * dy + n.dot(fwd)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (it["dist"] - n.dot(eye)) / nd
        ok = inside & (t > 0) & np.isfinite(t)
        zb = zbuf[y0:y1, x0:x1]
        ok &= t < zb
        if not ok.any():
            return
        if it["sky"]:
            if write:
                zb[ok] = t[ok]
                skymask[y0:y1, x0:x1][ok] = True
            return
        if not shade:
            zb[ok] = t[ok]
            return
        local_eye = eye - it["org"]
        vs = it["vecs"]
        ray = lambda k: vs[k, :3].dot(right) * dx + vs[k, :3].dot(up) * dy + vs[k, :3].dot(fwd)  # noqa: E731
        s = vs[0, :3].dot(local_eye) + vs[0, 3] + t * ray(0)
        tt = vs[1, :3].dot(local_eye) + vs[1, 3] + t * ray(1)
        tex = it["tex"]
        if tex is not None:
            pix, pal = tex
            th, tw = pix.shape
            idx = pix[np.floor(tt).astype(np.int64) % th, np.floor(s).astype(np.int64) % tw]
            if it["masked"]:
                ok &= idx != 255
            col = pal[idx].astype(np.float32)
        else:
            col = np.full(s.shape + (3,), 128, np.float32)
        if it["lm"] is not None:
            lm = it["lm"]
            lh, lw = lm.shape[:2]
            ls = np.clip(s / 16.0 - it["lmins"][0], 0, lw - 1)
            lt = np.clip(tt / 16.0 - it["lmins"][1], 0, lh - 1)
            i0, j0 = np.floor(lt).astype(np.int64), np.floor(ls).astype(np.int64)
            i1, j1 = np.minimum(i0 + 1, lh - 1), np.minimum(j0 + 1, lw - 1)
            fi, fj = (lt - i0)[..., None], (ls - j0)[..., None]
            light = (lm[i0, j0] * (1 - fi) * (1 - fj) + lm[i0, j1] * (1 - fi) * fj +
                     lm[i1, j0] * fi * (1 - fj) + lm[i1, j1] * fi * fj)
        elif it["water"]:
            light = np.full(col.shape, 150, np.float32)
        else:
            light = np.full(col.shape, 90, np.float32)
        col = col * (np.power(light / 255.0, 0.55) * 1.55)    # гамма как у движка, с запасом на пересвет
        sub = img[y0:y1, x0:x1]
        if write:
            zb[ok] = t[ok]
            sub[ok] = col[ok]
            skymask[y0:y1, x0:x1][ok] = False
        elif it["mode"] == "add":
            sub[ok] = sub[ok] + col[ok] * it["alpha"]
        else:
            sub[ok] = sub[ok] * (1 - it["alpha"]) + col[ok] * it["alpha"]

    vis = (bsp.nrm.dot(eye) - bsp.dst > 0.01) & ((bsp.cen - eye).dot(fwd) + bsp.rad > near)
    for k in np.nonzero(vis)[0]:
        it = bsp.items[k]
        if it["mode"] == "solid":
            raster(it, True)
        else:
            translucent.append(it)
    if shade:
        for it in translucent:
            raster(it, False)
        return np.clip(img, 0, 255).astype(np.uint8), zbuf, skymask
    return None, zbuf, skymask


def choose_view(bsp, eye_h=28.0, pitch=6.0):
    """The most open view from the spawn points: (eye, yaw, pitch)."""
    best = None
    sp = bsp.spawns()
    if not sp:
        mdl = bsp.models[0]
        sp = [(((mdl["mins"] + mdl["maxs"]) / 2.0).astype(np.float64), 0.0)]
    for o, yaw in sp[:16]:
        eye = o + np.array([0, 0, eye_h])
        for dyaw in (0, 30, -30, 60, -60, 90, -90, 180):
            _, z, sky = render(bsp, eye, yaw + dyaw, pitch, 160, 90, shade=False)
            fin = np.isfinite(z) & ~sky
            if fin.mean() < 0.5:
                continue
            depth = np.log(np.clip(z[fin], 16, 4096))
            close = (z[fin] < 128).mean()
            zc = z[30:60, 53:107]
            centre = np.median(np.where(np.isfinite(zc), zc, 4096))
            score = (depth.mean() + 0.6 * depth.std() - 4.0 * close
                     - 1.5 * max(0, sky.mean() - 0.35) - (1.0 if centre < 300 else 0.0)
                     - 0.1 * abs(dyaw) / 90.0)
            if best is None or score > best[0]:
                best = (score, eye, yaw + dyaw)
    if best is None:
        o, yaw = sp[0]
        best = (0, o + np.array([0, 0, eye_h]), yaw)
    return best[1], best[2], pitch
