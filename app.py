#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Веб-панель выделенного сервера Counter-Strike 1.5 (HLDS: WON 3.1.1.x или Steam).

Управление сервером и статистика в браузере: игроки и боты, карты (порядок, картинки),
настройки server.cfg, статистика по живому логу, логи, консоль rcon, журнал действий.
Все настройки — в .env рядом с этим файлом (образец — .env.example, описание — config.py).

    python3 app.py            — запустить панель
    python3 app.py --check    — проверить настройки: файлы, сервер, rcon — и выйти
    python3 app.py --init     — новый пароль панели (хэш и ключ сессий запишутся в .env)

Особенности старого движка, которые учитывает панель:
  * список игроков и заходы — из живого лога (live.py), а не из rcon status: WON-сервер
    пишет каждую rcon-команду в свой лог вместе с паролем;
  * названия карты в логе WON-сервера нет — панель узнаёт его запросом info при смене карты;
  * порядок карт — свой файл панели, список для движка (mapcycle.txt) строит mapcycle.py;
  * живые игроки считаются по IP (ники бывают одинаковые), страна — из базы GeoLite2 (geo.py).
"""

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import sys
import tempfile
import time

from aiohttp import web

import audit as audit_mod
import backups as backups_mod
import cfg as cfg_mod
import config as config_mod
import geo as geo_mod
import hl as hl_mod
import humans
import live as live_mod
import logline
import stats as stats_mod
import sysinfo as sys_mod
from passwords import check_password

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
SESSION_TTL = 12 * 3600
COOKIE = "hlp"

# типы файлов оформления: в старых Python их нет в mimetypes. aiohttp 3.10+ отдаёт статику
# по своей таблице (web_fileresponse.CONTENT_TYPES) — дописываем и туда
try:
    from aiohttp import web_fileresponse
    _TYPES = [mimetypes, getattr(web_fileresponse, "CONTENT_TYPES", mimetypes)]
except ImportError:
    _TYPES = [mimetypes]
for ext, mime in ((".webp", "image/webp"), (".woff2", "font/woff2"), (".woff", "font/woff"), (".ttf", "font/ttf"),
                  (".mp3", "audio/mpeg"), (".ogg", "audio/ogg"), (".wav", "audio/wav"), (".webm", "video/webm"),
                  (".svg", "image/svg+xml"), (".js", "text/javascript")):
    for _t in _TYPES:
        _t.add_type(mime, ext)


# --- сессии --------------------------------------------------------------

class Sessions:
    """Подписанная кука: переживает перезапуск панели и не требует базы."""

    def __init__(self, secret):
        self.secret = secret.encode()

    def _sig(self, text):
        return hmac.new(self.secret, text.encode(), hashlib.sha256).hexdigest()

    def make(self):
        body = "%d.%s" % (int(time.time()) + SESSION_TTL, secrets.token_hex(8))
        return body + "." + self._sig(body)

    def valid(self, value):
        try:
            expiry, nonce, sig = (value or "").split(".")
        except ValueError:
            return False
        return hmac.compare_digest(sig, self._sig(expiry + "." + nonce)) and int(expiry) > time.time()

    def csrf(self, value):
        return self._sig("csrf:" + value)[:32]


def same_value(live, value):
    """Значение на сервере совпадает с записанным? 20 и 20.000000 — одно и то же."""
    a, b = str(live).strip().strip('"'), str(value).strip().strip('"')
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return a == b


# --- ошибки и проверки ввода ----------------------------------------------

class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def need(cond, message):
    if not cond:
        raise ApiError(message)


def int_arg(value, lo, hi, what="число"):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ApiError("%s: нужно целое число" % what)
    need(lo <= n <= hi, "%s: от %d до %d" % (what, lo, hi))
    return n


def ip_arg(value):
    value = (value or "").strip()
    need(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", value) and all(int(x) < 256 for x in value.split(".")),
         "нужен IPv4-адрес, например 1.2.3.4")
    return value


def text_arg(value, maxlen=120):
    """Текст для чата: без кавычек, точек с запятой и переводов строк — иначе
    он мог бы закрыть кавычку и превратиться в ещё одну команду."""
    value = re.sub(r'["\\;\r\n\x00-\x1f]', " ", str(value or "")).strip()
    need(value, "пустой текст")
    return value[:maxlen]


def ok(data=None, **extra):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return web.json_response(body)


# --- приложение ------------------------------------------------------------

class Panel:
    def __init__(self, cfg):
        self.conf = cfg
        os.makedirs(cfg.data, exist_ok=True)
        db = os.path.join(cfg.data, "panel.db")

        self.hl = hl_mod.HLServer(cfg.hl_host, cfg.hl_port, cfg.rcon_password, cfg.rcon_cfg)
        files = cfg_mod.Files(os.path.join(cfg.data, "cfg-backups"))
        self.cfg = cfg_mod.ServerConfig(cfg.server_cfg, files)
        self.bots_cfg = cfg_mod.bot_config(cfg.bots_cfg, files)
        self.pool = cfg_mod.MapPool(cfg.mappool, cfg.mapcycle, cfg.maps_dirs, files)
        self.files = files
        self.listip = cfg.listip
        self.audit = audit_mod.Audit(db)
        self.live = live_mod.Live(db, cfg.live_log)
        self.stats = stats_mod.Stats(db, cfg.live_log)
        self.backups = backups_mod.Backups(db, cfg.backup_dir, cfg.backup_days)
        # фоновые записи в базу и восстановление копии статистики идут по очереди
        self.db_lock = asyncio.Lock()
        self.sys = sys_mod.System(cfg)
        self.sessions = Sessions(cfg.secret)
        self.password_hash = cfg.password_hash
        self.login_fails = []
        # карта, от которой список карт уже выровнен (см. keep_order)
        self.order_synced = None
        self.geo = geo_mod.Geo(cfg.geoip)
        # настройки, которые ждут смены карты или перезапуска: имя → {kind, value, at}
        self.pending = {}
        self.hostname = ""          # последнее имя сервера — для заголовка, пока он молчит

    def features(self):
        """Что есть у этого сервера: от этого зависят кнопки и карточки в панели."""
        f = self.conf.features()
        f["music"] = bool(self.music())
        f["art"] = bool(self._static_files("maps", (".jpg",)))
        f["sfx"] = bool(self._static_files(os.path.join("hl", "sfx"), (".wav",)))
        f["logo"] = os.path.exists(os.path.join(STATIC, "hl", "logo.webm"))
        f["geo"] = any(os.path.exists(x) for x in self.conf.geoip)
        return f

    @staticmethod
    def _static_files(sub, exts):
        try:
            return sorted(f for f in os.listdir(os.path.join(STATIC, sub)) if f.lower().endswith(exts))
        except OSError:
            return []

    def music(self):
        """Мелодии из static/music: [{file, title, author, license}]. Названия и авторы — из
        static/music/tracks.json и tracks.local.json, порядок тоже оттуда (первая играет первой);
        файлы, которых там нет, идут следом с названием из имени файла."""
        files = self._static_files("music", (".mp3", ".ogg"))
        known = []
        # tracks.local.json — мелодии из своей копии игры (tools/build_assets.py), в репозиторий не входят
        for name in ("tracks.json", "tracks.local.json"):
            try:
                with open(os.path.join(STATIC, "music", name), encoding="utf-8") as f:
                    known += [t for t in json.load(f) if isinstance(t, dict) and t.get("file") in files]
            except (OSError, ValueError):
                pass
        listed = {t["file"] for t in known}
        rest = [{"file": f, "title": os.path.splitext(f)[0].replace("-", " ").replace("_", " ").strip().title()}
                for f in files if f not in listed]
        return [{k: t.get(k, "") for k in ("file", "title", "author", "license")} for t in known] + rest

    def site(self):
        """Название, адрес и что есть на сервере — для меню и экрана входа."""
        return {"title": self.conf.title or self.hostname or "", "hub": self.conf.hub,
                "address": self.address(), "features": self.features(), "music": self.music()}

    def address(self):
        return self.conf.public_address or "%s:%s" % (self.conf.hl_host, self.conf.hl_port)

    # --- помощники ------------------------------------------------------

    async def blocking(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    async def db_write(self, fn):
        """Запись в базу из фона — не во время восстановления копии. fn без аргументов
        (lambda: self.live.tick()): self.live после восстановления — новый."""
        async with self.db_lock:
            return await self.blocking(fn)

    async def rcon(self, action, command, detail=""):
        """rcon с записью в журнал. Ошибку превращает в понятный ответ."""
        try:
            out = await self.hl.rcon(command)
        except RuntimeError as e:
            self.audit.log(action, detail or command, ok=False, output=str(e))
            raise ApiError("Сервер: %s" % e, 502)
        out = logline.redact(out)
        self.audit.log(action, detail or command, ok=True, output=out)
        return out

    async def apply_cycle(self, after):
        """Переписать mapcycle.txt так, чтобы первой шла карта после after, и заставить
        движок перечитать его. Игровая библиотека перечитывает список только при смене
        имени в cvar mapcyclefile, поэтому имя переключается между mapcycle.txt и
        ./mapcycle.txt (это один и тот же файл). На ближайшей смене карты сервер возьмёт
        первую карту нового списка (проверено на тестовом сервере 04.10.2026).
        Возвращает (список, применён ли на ходу)."""
        seq = await self.blocking(self.pool.regenerate, after)
        self.order_synced = after
        try:
            out = await self.hl.rcon("mapcyclefile")
            m = re.search(r'"mapcyclefile" is "([^"]*)"', out)
            name = "mapcycle.txt" if m and m.group(1) != "mapcycle.txt" else "./mapcycle.txt"
            await self.hl.rcon("mapcyclefile " + name)
            return seq, True
        except RuntimeError:
            return seq, False  # сервер не отвечает — прочитает новый файл при запуске

    async def keep_order(self, current):
        """Следующей всегда должна идти карта после текущей. Если карту сменили мимо
        списка (из консоли, changelevel) или панель только запустилась, список
        переписывается от текущей карты."""
        if not current or current == self.order_synced:
            return
        prev, self.order_synced = self.order_synced, current
        order = await self.blocking(self.pool.pool)
        if prev in order and cfg_mod.MapPool.following(order, prev, 1) == [current]:
            return  # обычная смена по списку
        await self.apply_cycle(current)

    async def pending_list(self):
        """Настройки, которые ждут смены карты или перезапуска. Сами исчезают, когда
        карта сменилась (для «map») или контейнер перезапущен (для всех)."""
        started = await self.blocking(self.sys.started_ts) or 0
        since = self.live.map_since or 0
        for name, p in list(self.pending.items()):
            if started > p["at"] or (p["kind"] == "map" and since > p["at"]):
                del self.pending[name]
        return sorted(self.pending.values(), key=lambda p: p["at"])


    def humans_view(self, since):
        """Заходы за период + итоги, страны и рекорды за всё время — по IP."""
        recent = self.live.sessions(since)
        every = self.live.sessions(None, 20000)
        for r in recent:
            r["ip"] = humans.ip_of(r["address"])
            r["country"] = self.geo.country(r["ip"])
        players = humans.summarize(every, self.geo)
        return {"sessions": recent, "players": players, "countries": humans.countries(players),
                "records": humans.records(every, players),
                # вкладка «Сводка»
                "summary": {"top_killers": humans.top_killers(players), "maps": humans.human_maps(every),
                            "durations": humans.durations(every), "newcomers": humans.newcomers(players)}}

    def player_card(self, ip):
        every = self.live.sessions(None, 20000)
        names = []
        for r in every:
            if humans.ip_of(r["address"]) == ip and r["name"] not in names:
                names.append(r["name"])
        return humans.card(ip, every, self.geo, self.stats.weapons_for(names), every,
                           players=humans.summarize(every, self.geo),
                           maps_log=self.stats.maps_by_names(names))

    def previews(self):
        """Карты, для которых есть картинка static/maps/<карта>.jpg."""
        try:
            return sorted(f[:-4] for f in os.listdir(os.path.join(BASE, "static", "maps")) if f.endswith(".jpg"))
        except OSError:
            return []

    def bans(self):
        """Баны по IP — прямо из listip.cfg (его пишет writeip), без rcon."""
        rows = []
        try:
            with open(self.listip, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(r"^\s*addip\s+([\d.]+)\s+(\d{1,3}(?:\.\d{1,3}){3})", line)
                    if m:
                        minutes = float(m.group(1))
                        rows.append({"ip": m.group(2), "minutes": minutes})
        except OSError:
            pass
        return rows

    def online(self, server_players):
        """Кто на сервере: живой лог (userid, адрес, бот ли) + запрос players (фраги, время)."""
        by_name = {p["name"]: p for p in (server_players or [])}
        rows, seen = [], set()
        for p in sorted(self.live.players.values(), key=lambda x: x["uid"]):
            q = by_name.get(p["name"])
            if server_players is not None and q is None:
                continue
            seen.add(p["name"])
            rows.append({"uid": p["uid"], "name": p["name"], "bot": p["bot"], "address": p["address"],
                         "team": p.get("team", ""),
                         "frags": q["frags"] if q else None, "time": q["time"] if q else None})
        for name, q in by_name.items():
            if name not in seen:  # зашёл до того, как панель начала читать лог
                rows.append({"uid": None, "name": name, "bot": None, "address": "", "team": "",
                             "frags": q["frags"], "time": q["time"]})
        return rows

    # --- вход -----------------------------------------------------------

    async def me(self, request):
        if not self.conf.title and not self.hostname:
            # имя сервера для экрана входа — до входа обзор ещё никто не открывал
            info = await self.hl.info()
            self.hostname = info["hostname"] if info else ""
        cookie = request.cookies.get(COOKIE, "")
        if self.sessions.valid(cookie):
            return ok({"auth": True, "csrf": self.sessions.csrf(cookie), "site": self.site()})
        return ok({"auth": False, "site": self.site()})

    async def login(self, request):
        now = time.time()
        self.login_fails = [t for t in self.login_fails if now - t < 300]
        if len(self.login_fails) >= 5:
            raise ApiError("Слишком много неверных попыток. Подождите 5 минут.", 429)
        body = await request.json()
        if not check_password(str(body.get("password", "")), self.password_hash):
            self.login_fails.append(now)
            self.audit.log("вход", "неверный пароль", ok=False)
            await asyncio.sleep(1)
            raise ApiError("Неверный пароль", 403)
        self.login_fails.clear()
        cookie = self.sessions.make()
        self.audit.log("вход", "успешно")
        resp = ok({"auth": True, "csrf": self.sessions.csrf(cookie), "site": self.site()})
        resp.set_cookie(COOKIE, cookie, max_age=SESSION_TTL, httponly=True, samesite="Strict", path="/")
        return resp

    async def logout(self, request):
        resp = ok()
        resp.del_cookie(COOKIE, path="/")
        return resp

    # --- обзор ----------------------------------------------------------

    async def overview(self, request):
        info = await self.hl.info()
        players = await self.hl.players() if info else None
        rules = await self.hl.rules() if info else {}
        container = await self.blocking(self.sys.container_info)
        host = await self.blocking(self.sys.host_info)
        server = None
        if info is not None:
            self.hostname = info["hostname"]
            rows = self.online(players)
            bots = sum(1 for p in rows if p["bot"])
            since = self.live.map_since if self.live.current_map == info["map"] else None
            order = await self.blocking(self.pool.pool)
            nxt = cfg_mod.MapPool.following(order, info["map"], 1)
            pics = set(await self.blocking(self.previews))
            server = {
                "hostname": info["hostname"], "map": info["map"], "map_since": since,
                "next": nxt[0] if nxt else None,
                "preview": info["map"] in pics, "next_preview": bool(nxt) and nxt[0] in pics,
                "maxplayers": info["maxplayers"], "players": rows,
                "humans": len(rows) - bots, "bots": bots,
                "timelimit": rules.get("mp_timelimit", ""), "fraglimit": rules.get("mp_fraglimit", ""),
                "maxrounds": rules.get("mp_maxrounds", ""), "winlimit": rules.get("mp_winlimit", ""),
                "roundtime": rules.get("mp_roundtime", ""),
                # счёт раундов этой карты (из живого лога)
                "score": {"ct": self.live.score["ct"], "t": self.live.score["t"]} if since else None,
                "address": self.address(),
            }
        return ok({
            "server": server, "container": container, "host": host,
            "started": None if container else await self.blocking(self.sys.started_ts),
            "events": await self.blocking(self.sys.server_events),
            "stats": await self.blocking(self.stats.totals),
            "pending": await self.pending_list(),
            "now": int(time.time()),
        })

    # --- игроки ---------------------------------------------------------

    async def players(self, request):
        server_players = await self.hl.players()
        return ok({"players": self.online(server_players), "responding": server_players is not None,
                   "bans": await self.blocking(self.bans),
                   "bots": await self.blocking(self.bots_cfg.settings) if self.features()["bots"] else None,
                   "bots_kind": self.bots_cfg.kind})

    async def player_action(self, request):
        body = await request.json()
        action = body.get("action")
        name = str(body.get("name", ""))[:40]
        if action == "kick":
            uid = int_arg(body.get("uid"), 1, 1000000, "userid")
            out = await self.rcon("кик", "kick # %d" % uid, "%s (userid %d)" % (name, uid))
        elif action == "ban":
            uid = int_arg(body.get("uid"), 1, 1000000, "userid")
            ip = ip_arg(body.get("address"))
            out = await self.rcon("бан", "addip 0 %s" % ip, "%s, %s" % (name, ip))
            out += "\n" + await self.rcon("бан", "writeip", "сохранить баны")
            out += "\n" + await self.rcon("кик", "kick # %d" % uid, "после бана: %s" % name)
        elif action == "ban_address":
            ip = ip_arg(body.get("address"))
            out = await self.rcon("бан", "addip 0 %s" % ip)
            out += "\n" + await self.rcon("бан", "writeip", "сохранить баны")
        elif action == "unban":
            ip = ip_arg(body.get("address"))
            out = await self.rcon("снятие бана", "removeip %s" % ip)
            out += "\n" + await self.rcon("снятие бана", "writeip", "сохранить баны")
        elif action == "say":
            out = await self.rcon("сообщение всем", "say %s" % text_arg(body.get("text")))
        elif action == "bots" and self.bots_cfg.kind == "yapb":
            need(self.features()["bots"], "боты не настроены (BOTS_CFG в .env)")
            values = {"yb_quota": str(int_arg(body.get("quota"), 0, 31, "ботов")),
                      "yb_quota_mode": str(body.get("mode", "")),
                      "yb_difficulty": str(int_arg(body.get("difficulty"), 0, 4, "сложность"))}
            for key, value in values.items():
                try:
                    self.bots_cfg.check(key, value)
                except (KeyError, ValueError) as e:
                    raise ApiError("%s: %s" % (key, e))
            out = ""
            for key, value in values.items():
                old, new, backup = await self.blocking(self.bots_cfg.set_value, key, value)
                out += await self.rcon("боты", self.bots_cfg.apply_cmd(key, value), "%s: %s → %s" % (key, old, new)) + "\n"
        elif action == "kickbots" and self.bots_cfg.kind == "yapb":
            need(self.features()["bots"], "боты не настроены (BOTS_CFG в .env)")
            # yb_quota 0 до перезапуска (yapb.cfg не трогаем), потом выкинуть тех, кто есть
            out = await self.rcon("боты", "yb_quota 0", "убрать всех ботов до перезапуска")
            out += "\n" + await self.rcon("боты", "yb removebots", "убрать всех ботов")
        elif action == "bots":
            need(self.features()["bots"], "боты не настроены (BOTS_CFG в .env)")
            lo = int_arg(body.get("min_bots"), 0, 15, "минимум ботов")
            hi = int_arg(body.get("max_bots"), 0, 15, "максимум игроков с ботами")
            skill = int_arg(body.get("botskill"), 1, 5, "сложность")
            need(lo <= hi or hi == 0, "минимум ботов не может быть больше максимума")
            out = ""
            for key, value in (("min_bots", lo), ("max_bots", hi), ("botskill", skill)):
                old, new, backup = await self.blocking(self.bots_cfg.set_value, key, str(value))
                out += await self.rcon("боты", "jk_botti %s %d" % (key, value), "%s: %s → %s" % (key, old, new)) + "\n"
        elif action == "kickbots":
            need(self.features()["bots"], "боты не настроены (BOTS_CFG в .env)")
            out = await self.rcon("боты", "jk_botti min_bots 0", "убрать всех ботов до перезапуска")
            out += "\n" + await self.rcon("боты", "jk_botti max_bots 0", "убрать всех ботов до перезапуска")
            for p in list(self.live.players.values()):
                if p["bot"]:
                    out += "\n" + await self.rcon("кик", "kick # %d" % p["uid"], "бот %s" % p["name"])
        else:
            raise ApiError("неизвестное действие")
        return ok({"output": out})

    # --- карты ----------------------------------------------------------

    async def maps(self, request):
        info = await self.hl.info()
        rules = await self.hl.rules() if info else {}
        current = info["map"] if info else None
        order = await self.blocking(self.pool.order)
        upcoming = cfg_mod.MapPool.following([m["name"] for m in order if m["on"]], current)
        since = self.live.map_since if self.live.current_map == current else None
        try:
            limit = float(rules.get("mp_timelimit", 0) or 0)
        except ValueError:
            limit = 0
        return ok({
            "current": current, "map_since": since, "timelimit": limit,
            "ends_at": int(since + limit * 60) if since and limit else None,
            "order": order, "upcoming": upcoming,
            "available": await self.blocking(self.pool.available),
            "previews": await self.blocking(self.previews),
            "pending": await self.pending_list(),
            "now": int(time.time()),
        })

    async def map_action(self, request):
        body = await request.json()
        action = body.get("action")
        available = await self.blocking(self.pool.available)
        info = await self.hl.info()
        if action == "map":
            name = str(body.get("map", "")).lower()
            need(name in available, "такой карты нет на сервере")
            out = await self.rcon("смена карты", "changelevel %s" % name)
            await self.apply_cycle(name)  # дальше — по порядку от этой карты
        elif action == "next":
            pool = await self.blocking(self.pool.pool)
            need(pool, "нет включённых карт")
            name = cfg_mod.MapPool.following(pool, info["map"] if info else None, 1)[0]
            out = await self.rcon("следующая карта", "changelevel %s" % name)
            await self.apply_cycle(name)
        elif action == "restart":
            need(info, "сервер не отвечает")
            out = await self.rcon("перезапуск карты", "changelevel %s" % info["map"])
        elif action == "restartround":
            # рестарт игры на той же карте: счёт, деньги и оружие — с нуля, через 1 секунду
            need(info, "сервер не отвечает")
            out = await self.rcon("рестарт раунда", "sv_restartround 1")
        else:
            raise ApiError("неизвестное действие")
        return ok({"output": out})

    async def save_pool(self, request):
        """Порядок карт и выключенные. Работает сразу — со следующей смены карты."""
        body = await request.json()
        items = body.get("maps")
        need(isinstance(items, list) and 1 <= len(items) <= 200, "пустой список карт")
        available = set(await self.blocking(self.pool.available))
        maps, seen = [], set()
        for it in items:
            need(isinstance(it, dict), "неверный формат списка")
            name = str(it.get("name", "")).lower()
            need(name in available, "нет на сервере: %s" % name[:40])
            need(name not in seen, "карта дважды: %s" % name)
            seen.add(name)
            maps.append((name, bool(it.get("on"))))
        on = [m for m, enabled in maps if enabled]
        need(on, "включите хотя бы одну карту")
        backup = await self.blocking(self.pool.set_order, maps)
        info = await self.hl.info()
        try:
            seq, applied = await self.apply_cycle(info["map"] if info else None)
        except RuntimeError as e:
            raise ApiError("порядок сохранён, но список для сервера не записан: %s" % e, 500)
        off = [m for m, enabled in maps if not enabled]
        if off:
            detail = "по порядку: %s · выключены: %s" % (", ".join(on), ", ".join(off))
        else:
            detail = "по порядку: %s" % ", ".join(on)
        self.audit.log("карты", detail, output="копия: " + os.path.basename(backup))
        return ok({"backup": os.path.basename(backup), "next": seq[0] if applied else None, "applied": applied})

    # --- настройки ------------------------------------------------------

    async def settings(self, request):
        items = await self.blocking(self.cfg.settings)
        rules = await self.hl.rules()
        live = {k.lower(): v for k, v in (rules or {}).items()}
        for it in items:
            it["live"] = None if it["secret"] else live.get(it["name"].lower())
        bots = await self.blocking(self.bots_cfg.settings) if self.features()["bots"] else []
        return ok({"settings": items + bots, "backups": self.files.list_backups(),
                   "pending": await self.pending_list()})

    async def save_setting(self, request):
        body = await request.json()
        name = (body.get("name") or "").strip()
        need(re.fullmatch(r"[A-Za-z_]\w{0,40}", name), "недопустимое имя настройки")
        value = str(body.get("value", ""))
        need('"' not in value and "\n" not in value and ";" not in value,
             "в значении нельзя использовать кавычки, ; и переводы строк")
        need(len(value) <= 120, "слишком длинное значение")
        if body.get("bot"):
            need(self.features()["bots"], "боты не настроены (BOTS_CFG в .env)")
            try:
                old, new, backup = await self.blocking(self.bots_cfg.set_value, name, value)
            except (KeyError, ValueError) as e:
                raise ApiError(str(e))
            self.audit.log("настройка ботов", "%s: %s → %s" % (name, old, new),
                           output="копия: " + os.path.basename(backup))
            applied = True
            try:
                await self.hl.rcon(self.bots_cfg.apply_cmd(name, value))
            except RuntimeError:
                applied = False
            return ok({"backup": os.path.basename(backup), "applied_live": applied, "note": ""})
        try:
            old, new, backup = await self.blocking(self.cfg.set_value, name, value)
        except KeyError as e:
            raise ApiError(str(e), 404)
        except ValueError as e:
            raise ApiError(str(e))
        secret = name.lower() in cfg_mod.SECRETS
        self.audit.log("настройка", "%s: %s → %s" % (name, "***" if secret else old, "***" if secret else new),
                       output="копия: " + os.path.basename(backup))
        note = cfg_mod.RESTART_ONLY.get(name.lower(), "")
        # now — работает сразу; map — после смены карты; restart — сервер не принял
        # на ходу, нужен перезапуск; offline — сервер не отвечает, прочитает при запуске
        apply = "map" if note else "now"
        applied = False
        if not note:
            try:
                await self.hl.rcon('%s "%s"' % (name, value))
                applied = True
            except RuntimeError:
                apply = "offline"
        if applied and not secret:
            live = {k.lower(): v for k, v in (await self.hl.rules() or {}).items()}
            if name.lower() in live and not same_value(live[name.lower()], value):
                apply, applied = "restart", False
        if apply in ("map", "restart"):
            self.pending[name] = {"name": name, "value": "***" if secret else value, "kind": apply, "at": time.time()}
        else:
            self.pending.pop(name, None)
        return ok({"backup": os.path.basename(backup), "applied_live": applied, "note": note, "apply": apply})

    async def pending_view(self, request):
        return ok(await self.pending_list())

    async def pending_action(self, request):
        body = await request.json()
        need(body.get("action") == "dismiss", "неизвестное действие")
        self.pending.clear()
        return ok([])

    # --- статистика, логи, консоль, контейнер, журнал --------------------

    async def stats_view(self, request):
        s = self.stats
        return ok({
            "totals": await self.blocking(s.totals),
            "state": await self.blocking(s.state),
            "humans": await self.blocking(s.top, False, 50),
            "bots": await self.blocking(s.top, True, 40),
            "weapons_humans": await self.blocking(s.weapons, False),
            "weapons_bots": await self.blocking(s.weapons, True),
            "maps": await self.blocking(s.maps, 40),
            "objectives": await self.blocking(s.objectives, 25),
            "recent": await self.blocking(s.recent, 30),
            "activity": await self.blocking(s.activity, self._tz(request)),
        })

    @staticmethod
    def _tz(request):
        """Смещение браузера в минутах, как у JS getTimezoneOffset (Москва = -180)."""
        try:
            return max(-840, min(840, int(request.query.get("tz", 0))))
        except ValueError:
            return 0

    async def player_sessions(self, request):
        days = int_arg(request.query.get("days", 400), 1, 3650, "дней")
        data = await self.blocking(self.humans_view, time.time() - days * 86400)
        data.update({"tracking_since": await self.blocking(self.live.since), "now": int(time.time())})
        return ok(data)

    async def player(self, request):
        ip = request.query.get("ip", "")
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            raise ApiError("неверный адрес")
        card = await self.blocking(self.player_card, ip)
        need(card, "с этого адреса никто не заходил")
        return ok(card)

    async def logs(self, request):
        key = request.query.get("log", "live")
        need(key in ("live", "console", "hlds"), "нет такого лога")
        lines = int_arg(request.query.get("lines", 300), 10, 3000, "строк")
        grep = request.query.get("grep", "")[:100]
        rows = await self.blocking(self.sys.tail, key, lines, grep)
        return ok({"lines": rows, "files": self.sys.log_files()})

    async def console(self, request):
        body = await request.json()
        command = (body.get("command") or "").strip()
        need(command, "пустая команда")
        need(len(command) <= 300 and "\n" not in command and "\r" not in command,
             "команда должна быть одной строкой до 300 символов")
        need(not re.match(r"(?i)^\s*rcon_password\b", command), "пароль rcon меняется в конфиге сервера, не из панели")
        return ok({"output": await self.rcon("консоль", command)})

    async def commands(self, request):
        kind = self.bots_cfg.kind if self.features()["bots"] else None
        return ok([{"cmd": c, "help": h} for c, h, need_ in hl_mod.COMMANDS if not need_ or need_ == kind])

    async def container(self, request):
        body = await request.json()
        action = body.get("action")
        need(action in ("restart", "stop", "start"), "недопустимое действие")
        need(self.sys.can_restart(), "перезапуск не настроен (CONTAINER или RESTART_CMD в .env)")
        need(self.conf.container or action == "restart", "без Docker можно только перезапустить сервер")
        note = ""
        if action in ("restart", "start"):
            # свежий список карт: сервер встанет на свою стартовую карту (+map в командной
            # строке) и прочитает список при первой смене карты
            try:
                start_map = ((await self.blocking(self.sys.container_info)) or {}).get("start_map") or None
                await self.blocking(self.pool.restart_list, start_map)
                self.order_synced = start_map
                note = "список карт обновлён"
            except RuntimeError as e:
                note = "список карт не обновился: %s" % e
        success, out = await self.blocking(self.sys.container_action, action)
        if success and action in ("restart", "start"):
            self.pending.clear()
        self.audit.log("сервер", "%s (%s)" % (action, note) if note else action, ok=success, output=out)
        need(success, "перезапуск: %s" % out[:300])
        return ok({"output": out})

    # --- копии статистики ---------------------------------------------

    async def backups_view(self, request):
        need(self.backups.days > 0, "копии статистики выключены (BACKUP_DAYS в .env)")
        return ok({"days": self.backups.days, "items": await self.blocking(self.backups.items)})

    async def backups_action(self, request):
        need(self.backups.days > 0, "копии статистики выключены (BACKUP_DAYS в .env)")
        body = await request.json()
        action = body.get("action")
        if action == "create":
            item = await self.blocking(self.backups.create, "manual")
            self.audit.log("копия статистики", item["name"])
        elif action == "restore":
            async with self.db_lock:
                try:
                    chosen, before = await self.blocking(self.backups.restore, str(body.get("name", "")))
                except (LookupError, ValueError) as e:
                    raise ApiError(str(e))
                # кто на сервере и заходы — заново по живому логу, с позиции из копии;
                # статистика дочитает лог с её позиции сразу
                self.live = live_mod.Live(self.live.db_path, self.conf.live_log)
                await self.blocking(self.live.bootstrap)
                await self.blocking(self.stats.update)
            self.order_synced = None
            self.audit.log("восстановление статистики", "из %s, прежняя сохранена в %s" % (chosen["name"], before["name"]))
        else:
            raise ApiError("неизвестное действие")
        return ok({"days": self.backups.days, "items": await self.blocking(self.backups.items)})

    async def backup_file(self, request):
        """Скачать копию: файл .db.gz, имя — с названием контейнера, чтобы на компьютере не путать серверы."""
        need(self.backups.days > 0, "копии статистики выключены (BACKUP_DAYS в .env)")
        name = request.query.get("name", "")
        try:
            path = self.backups.path_of(name)
        except LookupError as e:
            raise ApiError(str(e), 404)
        prefix = re.sub(r"[^\w.-]+", "_", self.conf.container) + "-" if self.conf.container else ""
        return web.FileResponse(path, headers={"Content-Type": "application/gzip",
                                               "Content-Disposition": 'attachment; filename="%s%s"' % (prefix, name)})

    async def backup_upload(self, request):
        """Копия с компьютера: тело запроса — сам файл. Проверяется и ложится в список («с компьютера»)."""
        need(self.backups.days > 0, "копии статистики выключены (BACKUP_DAYS в .env)")
        os.makedirs(self.backups.folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".upload", dir=self.backups.folder)
        try:
            size = 0
            with os.fdopen(fd, "wb") as f:
                # читаем потоком: client_max_size (256 КБ) — для обычных запросов, копия больше
                async for chunk in request.content.iter_chunked(65536):
                    size += len(chunk)
                    need(size <= backups_mod.MAX_UPLOAD, "файл больше %d МБ" % (backups_mod.MAX_UPLOAD // 2 ** 20))
                    f.write(chunk)
            need(size > 0, "пустой файл")
            try:
                item = await self.blocking(self.backups.add, tmp)
            except ValueError as e:
                raise ApiError(str(e))
        finally:
            os.remove(tmp)
        self.audit.log("копия статистики", "загружена с компьютера: %s" % item["name"])
        return ok({"item": item, "days": self.backups.days, "items": await self.blocking(self.backups.items)})

    async def audit_view(self, request):
        return ok(await self.blocking(self.audit.recent, 300))

    async def stats_refresh(self, request):
        return ok({"added": await self.db_write(self.stats.update)})

    # --- фоновое ------------------------------------------------------

    async def background(self, app):
        async def note_maps():
            """Карты для свежих «Log file started»: спросить сервер, что загрузилось."""
            pending, self.live.pending_maps = self.live.pending_maps, []
            for ts in pending:
                if time.time() - ts < 120:
                    info = await self.hl.info()
                    if info:
                        await self.db_write(lambda: self.live.set_map(ts, info["map"]))

        async def live_loop():
            try:
                await self.db_write(lambda: self.live.bootstrap())
                last = self.live.pending_maps[-1:] if self.live.pending_maps else []
                self.live.pending_maps = []
                info = await self.hl.info()
                if info and info["map"] != self.live.current_map:
                    await self.db_write(lambda: self.live.set_map(last[0] if last else time.time(), info["map"]))
            except Exception as e:
                print("live bootstrap: %r" % e, file=sys.stderr, flush=True)
            while True:
                try:
                    await self.db_write(lambda: self.live.tick())
                    await note_maps()
                except Exception as e:
                    print("live: %r" % e, file=sys.stderr, flush=True)
                await asyncio.sleep(3)

        async def reconcile_loop():
            await asyncio.sleep(10)
            while True:
                try:
                    players = await self.hl.players()
                    await self.db_write(lambda: self.live.reconcile(players))
                    info = await self.hl.info()
                    # смена карты, которую лог не принёс (первая карта после запуска сервера)
                    if info and info["map"] != self.live.current_map:
                        await self.db_write(lambda: self.live.set_map(time.time(), info["map"]))
                    if info:
                        await self.keep_order(info["map"])
                except Exception as e:
                    print("reconcile: %r" % e, file=sys.stderr, flush=True)
                await asyncio.sleep(20)

        async def stats_loop():
            await asyncio.sleep(15)
            while True:
                try:
                    await self.db_write(self.stats.update)
                except Exception as e:  # статистика не должна ронять панель
                    print("stats: %r" % e, file=sys.stderr, flush=True)
                await asyncio.sleep(60)

        async def backup_loop():
            # копия статистики раз в сутки (BACKUP_DAYS), старые убираются
            await asyncio.sleep(120)
            while self.backups.days > 0:
                try:
                    if await self.blocking(self.backups.due):
                        await self.blocking(self.backups.create, "auto")
                except Exception as e:
                    print("backup: %r" % e, file=sys.stderr, flush=True)
                await asyncio.sleep(3600)

        tasks = [asyncio.create_task(t()) for t in (live_loop, reconcile_loop, stats_loop, backup_loop)]
        transport = None
        addr = self.conf.log_udp_addr()
        if addr:
            # сервер шлёт каждую строку лога UDP-пакетом (logaddress) — дописываем в LIVE_LOG
            try:
                transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                    lambda: LogReceiver(self.conf.live_log), local_addr=addr)
            except OSError as e:
                print("live log: cannot listen on %s:%s: %s" % (addr[0], addr[1], e), file=sys.stderr, flush=True)
        yield
        for t in tasks:
            t.cancel()
        if transport:
            transport.close()


class LogReceiver(asyncio.DatagramProtocol):
    """Пакеты живого лога: FF FF FF FF «log » + строка. Пишем их в файл как есть — так же,
    как socat в контейнере; читает файл live.py. Файл открывается на каждую запись:
    stats.py обрезает его, когда он вырастает больше 10 МБ."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def datagram_received(self, data, addr):
        if not data.startswith(b"\xff\xff\xff\xff") or len(data) > 4096:
            return
        if not data.rstrip(b"\x00").endswith(b"\n"):
            data = data.rstrip(b"\x00") + b"\n"
        try:
            with open(self.path, "ab") as f:
                f.write(data)
        except OSError as e:
            print("live log: %s" % e, file=sys.stderr, flush=True)


def peer_allowed(remote, allowed):
    """Адрес из списка PANEL_ALLOWED_PEERS: точный адрес или сеть (192.168.0.0/24)."""
    try:
        ip = ipaddress.ip_address(remote or "")
    except ValueError:
        return False
    for item in allowed:
        try:
            if "/" in item:
                if ip in ipaddress.ip_network(item, strict=False):
                    return True
            elif ip == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False


# --- промежуточные слои ----------------------------------------------------

def build_app(panel):
    open_paths = {"/api/me", "/api/login"}

    @web.middleware
    async def guard(request, handler):
        # пускаем только с адресов PANEL_ALLOWED_PEERS (по умолчанию — с этой же машины:
        # SSH-канал или обратный прокси приходят на 127.0.0.1)
        if not peer_allowed(request.remote, panel.conf.allowed_peers):
            raise web.HTTPForbidden(text="forbidden")
        try:
            if request.path.startswith("/api/") and request.path not in open_paths:
                cookie = request.cookies.get(COOKIE, "")
                if not panel.sessions.valid(cookie):
                    raise ApiError("Нужно войти", 401)
                if request.method == "POST":
                    token = request.headers.get("X-CSRF", "")
                    if not hmac.compare_digest(token, panel.sessions.csrf(cookie)):
                        raise ApiError("Устаревшая страница — обновите её", 403)
            resp = await handler(request)
        except ApiError as e:
            resp = web.json_response({"ok": False, "error": str(e)}, status=e.status)
        except web.HTTPException:
            raise
        except Exception as e:
            print("error %s: %r" % (request.path, e), file=sys.stderr, flush=True)
            resp = web.json_response({"ok": False, "error": "Внутренняя ошибка: %s" % e}, status=500)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; media-src 'self'; font-src 'self'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif request.path.endswith((".js", ".css")):
            # браузер каждый раз сверяется с панелью (ответ 304, если файл тот же):
            # иначе после обновления панели он неделями показывал бы старый скрипт
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app = web.Application(middlewares=[guard], client_max_size=256 * 1024)
    r = app.router
    r.add_get("/api/me", panel.me)
    r.add_post("/api/login", panel.login)
    r.add_post("/api/logout", panel.logout)
    r.add_get("/api/overview", panel.overview)
    r.add_get("/api/players", panel.players)
    r.add_post("/api/players", panel.player_action)
    r.add_get("/api/maps", panel.maps)
    r.add_post("/api/maps", panel.map_action)
    r.add_post("/api/pool", panel.save_pool)
    r.add_get("/api/sessions", panel.player_sessions)
    r.add_get("/api/player", panel.player)
    r.add_get("/api/pending", panel.pending_view)
    r.add_post("/api/pending", panel.pending_action)
    r.add_get("/api/settings", panel.settings)
    r.add_post("/api/settings", panel.save_setting)
    r.add_get("/api/stats", panel.stats_view)
    r.add_post("/api/stats/refresh", panel.stats_refresh)
    r.add_get("/api/logs", panel.logs)
    r.add_post("/api/console", panel.console)
    r.add_get("/api/commands", panel.commands)
    r.add_post("/api/container", panel.container)
    r.add_get("/api/audit", panel.audit_view)
    r.add_get("/api/backups", panel.backups_view)
    r.add_post("/api/backups", panel.backups_action)
    r.add_get("/api/backups/file", panel.backup_file)
    r.add_post("/api/backups/upload", panel.backup_upload)

    async def index(request):
        """Страница со ссылками на скрипты и стили с номером версии (время изменения
        файла): после обновления панели браузер точно возьмёт новые. Тот же номер в
        data-v у <html> — им boot.js подключает словарь языка."""
        with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
            page = f.read()
        newest = 0
        for name in ("app.js", "app.css", "boot.js"):
            try:
                ver = int(os.stat(os.path.join(STATIC, name)).st_mtime)
            except OSError:
                continue
            newest = max(newest, ver)
            page = page.replace("/static/%s\"" % name, "/static/%s?v=%d\"" % (name, ver))
        try:
            newest = max([newest] + [int(os.stat(os.path.join(STATIC, "i18n", f)).st_mtime)
                                     for f in os.listdir(os.path.join(STATIC, "i18n"))])
        except OSError:
            pass
        page = page.replace("<html ", '<html data-v="%d" ' % newest, 1)
        return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store"})
    r.add_get("/", index)
    r.add_static("/static/", STATIC)
    app.cleanup_ctx.append(panel.background)
    return app


# --- запуск ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--init", action="store_true", help="new random panel password (hash goes into .env)")
    ap.add_argument("--check", action="store_true", help="check the settings and the server, then exit")
    args = ap.parse_args()
    cfg = config_mod.Config()
    if args.init or args.check:
        import cli
        if args.init:
            cli.init_password(cfg)
            return
        sys.exit(cli.check_setup(cfg))
    if not cfg.path.exists():
        sys.exit("No settings file %s: copy .env.example to .env and fill it in (see README)." % cfg.path)
    if not cfg.secret or not cfg.password_hash:
        sys.exit("No panel password yet: run python3 app.py --init (or tools/passwd.py) first.")
    panel = Panel(cfg)
    host, port = cfg.panel_host, cfg.panel_port
    web.run_app(build_app(panel), host=host, port=port, access_log=None,
                print=lambda *_: print("Panel: http://%s:%s" % (host, port), flush=True))


if __name__ == "__main__":
    main()
