#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Команды панели для консоли: python3 app.py --init и python3 app.py --check.

Выводят текст по-английски — так же, как README и tools/: ими пользуются и те, кто ставит
панель с GitHub. В браузер отсюда ничего не уходит.
"""

import asyncio
import os
import secrets

import cfg as cfg_mod
import hl as hl_mod
from passwords import hash_password


def init_password(cfg):
    """A new random panel password: its hash and the session key go into .env (other lines are
    kept as they are), the password itself into PASSWORD_FILE (mode 600) and onto the screen."""
    password = secrets.token_urlsafe(12)
    values = {"PANEL_PASSWORD_HASH": hash_password(password), "PANEL_SECRET": cfg.secret or secrets.token_hex(32)}
    path = cfg.path
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values and "=" in line and not line.lstrip().startswith("#"):
            lines[i] = "%s=%s" % (key, values[key])
            done.add(key)
    lines += ["%s=%s" % (k, v) for k, v in values.items() if k not in done]
    old = os.umask(0o077)
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.makedirs(os.path.dirname(cfg.password_file) or ".", exist_ok=True)
        with open(cfg.password_file, "w", encoding="utf-8") as f:
            f.write(password + "\n")
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    os.chmod(cfg.password_file, 0o600)
    print("New panel password: %s\n(also saved to %s)\nRestart the panel to apply it." % (password, cfg.password_file))


def check_setup(cfg):
    """What the panel found and what it can reach. Exit code 1 if something is broken."""
    bad = 0

    def line(ok, what, detail=""):
        nonlocal bad
        mark = {True: "OK  ", False: "FAIL", None: " -  "}[ok]
        bad += ok is False
        print("[%s] %-24s %s" % (mark, what, detail))

    print("Settings file: %s" % cfg.path)
    line(cfg.path.exists(), ".env", "" if cfg.path.exists() else "missing: copy .env.example to .env")
    line(bool(cfg.password_hash and cfg.secret), "panel password",
         "set" if cfg.password_hash else "empty: run python3 app.py --init (or tools/passwd.py)")
    line(os.path.isdir(cfg.hl_dir or ""), "HL_DIR", cfg.hl_dir or "not set")
    line(os.path.exists(cfg.server_cfg), "server.cfg", cfg.server_cfg)
    line(os.path.exists(cfg.mapcycle) or None, "mapcycle.txt", cfg.mapcycle)
    maps = cfg_mod.MapPool(cfg.mappool, cfg.mapcycle, cfg.maps_dirs, None).available()
    line(bool(maps), "maps (*.bsp)", "%d in %s" % (len(maps), ", ".join(cfg.maps_dirs)))
    line(os.path.exists(cfg.mappool) or None, "map order", cfg.mappool + (
        "" if os.path.exists(cfg.mappool) else " (created on first save)"))
    server = hl_mod.HLServer(cfg.hl_host, cfg.hl_port, cfg.rcon_password, cfg.rcon_cfg)
    info = asyncio.run(server.info())
    line(bool(info), "server %s:%s" % (cfg.hl_host, cfg.hl_port),
         "%s, %s, %s/%s players, protocol %s (%s)" % (info["hostname"], info["map"], info["players"],
                                                       info["maxplayers"], info["protocol"], server.mode)
         if info else "no answer (is it running? HL_HOST/HL_PORT right?)")
    if info:
        try:
            out = asyncio.run(server.rcon("mapcyclefile"))
            line(True, "rcon", out.strip()[:70])
        except RuntimeError as e:
            line(False, "rcon", "%s (RCON_PASSWORD / rcon_password in RCON_CFG)" % e)
    if cfg.log_udp:
        cmd = "logaddress_add" if server.mode == "steam" else "logaddress"
        line(None, "live log", "the panel listens on %s and writes %s; server.cfg needs: log on + %s %s"
             % (cfg.log_udp, cfg.live_log, cmd, cfg.log_udp.replace(":", " ")))
    else:
        line(os.path.exists(cfg.live_log) or None, "live log", cfg.live_log + " (written by something else)")
    feats = cfg.features()
    line(None, "Docker", cfg.container or "no")
    line(None, "server restart", "docker restart" if cfg.container else (cfg.restart_cmd or "not configured"))
    line(feats["bots"] or None, "jk_botti bots", cfg.bots_cfg or "no")
    geo = next((x for x in cfg.geoip if os.path.exists(x)), "")
    line(bool(geo) or None, "countries (GeoLite2)", geo or "no database: countries are not shown")
    print("All good." if not bad else "Problems: %d." % bad)
    return 1 if bad else 0
