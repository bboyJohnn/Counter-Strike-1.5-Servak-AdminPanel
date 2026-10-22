#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кто сейчас на сервере и заходы живых игроков с точным временем.

Источник — живой лог (logs/live.log): строки приходят в ту же секунду, в каждой
есть дата и время. Раз в несколько секунд панель дочитывает новые строки:
  * обновляет список игроков на сервере (userid, имя, бот или человек, адрес,
    команда CT или T) и счёт раундов текущей карты —
    по нему работает раздел «Игроки», без rcon status каждые 15 секунд (каждая
    rcon-команда пишет в лог сервера пароль);
  * пишет заходы живых игроков в базу: вход по «connected»/«entered the game»,
    выход по «disconnected» или кику; убийства и смерти за заход.
Раз в 20 секунд список сверяется с публичным запросом players: если сервер
перезапустился и людей на нём нет, заход закрывается последним моментом, когда
игрок точно был на сервере.

Позиция чтения хранится в базе: после перезапуска панели строки, пришедшие, пока
она лежала, дочитываются и заходы не теряются.
"""

import os
import sqlite3
import time

import logline

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    uid        INTEGER,
    address    TEXT NOT NULL DEFAULT '',
    joined_at  INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL,
    left_at    INTEGER,
    maps       TEXT NOT NULL DEFAULT '',
    kills      INTEGER NOT NULL DEFAULT 0,
    deaths     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ps_joined ON player_sessions(joined_at DESC);
CREATE INDEX IF NOT EXISTS ps_open ON player_sessions(left_at);
CREATE TABLE IF NOT EXISTS map_starts (ts INTEGER PRIMARY KEY, map TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Сервер не видит игрока дольше этого — заход закрывается (перезапуск, обрыв).
LOST_AFTER = 180
BOOT_WINDOW = 2 * 1024 * 1024


class Live:
    def __init__(self, db_path, log_path):
        self.db_path = db_path
        self.log_path = log_path
        self.players = {}       # uid -> {uid, name, bot, address, since, team}
        # счёт раундов текущей карты: из строк «Team … triggered … (CT "x") (T "y")»
        self.score = {"ct": 0, "t": 0, "since": None}
        self.current_map = None
        self.map_since = None
        self.last_ts = 0
        self.skip_before = 0    # после обрезки лога: строки старше уже учтены
        self.pending_maps = []  # моменты «Log file started», для которых нужна карта
        with self._db() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('presence_since', ?)",
                       (str(int(time.time())),))
            row = db.execute("SELECT ts, map FROM map_starts ORDER BY ts DESC LIMIT 1").fetchone()
            if row:
                self.map_since, self.current_map = row["ts"], row["map"]
        # карта в том месте лога, которое сейчас читается (при дочитывании старых строк
        # она не совпадает с текущей): её получают новые заходы
        self.log_map, self.log_map_ts = self.current_map, self.map_since or 0

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(db, key, default=None):
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    @staticmethod
    def _set_meta(db, key, value):
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, str(value)))

    # --- чтение лога ------------------------------------------------------

    def _inode(self, st):
        return "%d:%d" % (st.st_dev, st.st_ino)

    def bootstrap(self):
        """При запуске панели: восстановить, кто на сервере (по хвосту лога), и
        дочитать заходы с сохранённой позиции."""
        if not os.path.exists(self.log_path):
            return
        st = os.stat(self.log_path)
        with open(self.log_path, "rb") as f:
            f.seek(max(0, st.st_size - BOOT_WINDOW))
            data = f.read()
        for ev in self._events(data, skip_first=st.st_size > BOOT_WINDOW):
            self._apply_live(*ev)
        self.tick(write_live=False)

    def _events(self, data, skip_first=False):
        rows = data.split(b"\n")
        if skip_first:
            rows = rows[1:]
        for raw in rows:
            parsed = logline.parse(logline.clean_line(raw))
            if parsed:
                yield parsed

    def tick(self, write_live=True):
        """Дочитывает новые строки. Возвращает число обработанных событий."""
        if not os.path.exists(self.log_path):
            return 0
        st = os.stat(self.log_path)
        inode = self._inode(st)
        with self._db() as db:
            offset = int(self._meta(db, "live_offset", 0))
            if self._meta(db, "live_inode", "") != inode or st.st_size < offset:
                # лог обрезали (панель сама переносит его в live.log.1) или заменили:
                # читаем с начала, но события, которые уже учтены, пропускаем
                offset = 0
                self.skip_before = int(self._meta(db, "live_ts", 0))
                self._set_meta(db, "live_inode", inode)
            if st.st_size == offset:
                return 0
            with open(self.log_path, "rb") as f:
                f.seek(offset)
                data = f.read(st.st_size - offset)
            cut = data.rfind(b"\n")
            if cut == -1:
                return 0
            n = 0
            for ts, kind, d in self._events(data[:cut + 1]):
                if ts < self.skip_before:
                    continue
                if kind == "map_name":
                    self._note_map(db, ts, d["map"])
                elif kind == "map_start":
                    # карта, которую панель уже узнала для этого момента (запросом info)
                    row = db.execute("SELECT map FROM map_starts WHERE ts BETWEEN ? AND ?"
                                     " ORDER BY ABS(ts - ?) LIMIT 1", (ts - 5, ts + 15, ts)).fetchone()
                    if row:
                        self.log_map, self.log_map_ts = row["map"], ts
                self._apply_session(db, ts, kind, d)
                if write_live:
                    self._apply_live(ts, kind, d)
                n += 1
                self.last_ts = max(self.last_ts, ts)
            self._set_meta(db, "live_offset", offset + cut + 1)
            self._set_meta(db, "live_ts", self.last_ts)
        return n

    # --- кто на сервере ---------------------------------------------------

    def _apply_live(self, ts, kind, d):
        if kind == "map_start":
            if not self.pending_maps or ts - self.pending_maps[-1] > 5:
                self.pending_maps.append(ts)
            self.score = {"ct": 0, "t": 0, "since": ts}
            return
        if kind == "team_win":
            if "ct" in d:
                self.score.update(ct=d["ct"], t=d["t"])
            return
        if kind == "world":
            # игра началась заново (зашёл второй игрок) или рестарт раунда — счёт с нуля
            if d["action"] == "Game_Commencing" or d["action"].startswith("Restart_Round"):
                self.score.update(ct=0, t=0)
            return
        if kind == "kill":
            for who in ("killer", "victim"):
                uid = d[who + "_uid"]
                if uid not in self.players:
                    self.players[uid] = {"uid": uid, "name": d[who], "bot": d[who + "_bot"],
                                         "address": "", "since": ts, "team": ""}
                if d.get(who + "_team"):
                    self.players[uid]["team"] = d[who + "_team"]
            return
        if kind not in ("connect", "enter", "disconnect", "kick", "rename", "suicide", "say", "team", "trigger"):
            return
        uid = d["uid"]
        if kind in ("disconnect", "kick"):
            self.players.pop(uid, None)
            return
        p = self.players.get(uid)
        if p is None:
            p = self.players[uid] = {"uid": uid, "name": d["name"], "bot": d["bot"],
                                     "address": "", "since": ts, "team": ""}
        if kind in ("team", "trigger") and d.get("team") is not None:
            p["team"] = d["team"]
        if kind == "connect":
            p["address"] = d.get("address", "")
            p["bot"] = d["bot"]
            p["since"] = ts
        elif kind == "rename":
            p["name"] = d["new"]
        else:
            p["bot"] = p["bot"] or d["bot"]

    def reconcile(self, server_players, now=None):
        """Сверка с публичным запросом players. server_players — список из hl.players()
        или None, если сервер молчит."""
        now = int(now or time.time())
        with self._db() as db:
            open_rows = [dict(r) for r in db.execute(
                "SELECT id, name, last_seen FROM player_sessions WHERE left_at IS NULL")]
            if server_players is None:
                for r in open_rows:
                    if now - r["last_seen"] > LOST_AFTER:
                        db.execute("UPDATE player_sessions SET left_at=? WHERE id=?", (r["last_seen"], r["id"]))
                return
            names = {p["name"] for p in server_players}
            for r in open_rows:
                if r["name"] in names:
                    db.execute("UPDATE player_sessions SET last_seen=? WHERE id=?", (now, r["id"]))
                elif now - r["last_seen"] > LOST_AFTER:
                    db.execute("UPDATE player_sessions SET left_at=? WHERE id=?", (r["last_seen"], r["id"]))
        # список «кто на сервере»: убираем тех, кого сервер не знает (перезапуск без
        # строк disconnected), если они не появились только что
        for uid, p in list(self.players.items()):
            if p["name"] not in names and now - p["since"] > 60:
                del self.players[uid]

    def set_map(self, ts, mapname):
        """Карта, загруженная в момент ts (узнана запросом info)."""
        if not mapname:
            return
        with self._db() as db:
            self._store_map(db, ts, mapname)

    def _note_map(self, db, ts, mapname):
        """Карта из строки лога «Loading map» / «Started map» (их пишет Steam-сервер).
        Обе строки об одной загрузке — запись одна."""
        if mapname == self.log_map and 0 <= ts - self.log_map_ts < 60:
            return
        self._store_map(db, ts, mapname)

    def _store_map(self, db, ts, mapname):
        db.execute("INSERT OR REPLACE INTO map_starts(ts, map) VALUES (?,?)", (int(ts), mapname))
        for r in db.execute("SELECT id, maps FROM player_sessions WHERE left_at IS NULL").fetchall():
            maps = [m for m in r["maps"].split(",") if m]
            if mapname not in maps:
                maps.append(mapname)
                db.execute("UPDATE player_sessions SET maps=? WHERE id=?", (",".join(maps), r["id"]))
        if ts >= self.log_map_ts:
            self.log_map, self.log_map_ts = mapname, int(ts)
        if self.map_since is None or ts >= self.map_since:
            self.current_map, self.map_since = mapname, int(ts)

    def map_start_of_current(self):
        return self.map_since

    # --- заходы -----------------------------------------------------------

    def _open_session(self, db, uid):
        return db.execute("SELECT id, maps FROM player_sessions WHERE left_at IS NULL AND uid=?"
                          " ORDER BY id DESC LIMIT 1", (uid,)).fetchone()

    def _apply_session(self, db, ts, kind, d):
        if kind == "kill":
            for who, col in (("killer", "kills"), ("victim", "deaths")):
                if d[who + "_bot"]:
                    continue
                row = self._open_session(db, d[who + "_uid"])
                # убийство своего (teamkill) — не фраг
                if row and not (who == "killer" and (d["killer_uid"] == d["victim_uid"] or d.get("teamkill"))):
                    db.execute("UPDATE player_sessions SET %s=%s+1, last_seen=MAX(last_seen, ?) WHERE id=?"
                               % (col, col), (ts, row["id"]))
            return
        if kind not in ("connect", "enter", "disconnect", "kick", "rename", "suicide", "say") or d["bot"]:
            return
        row = self._open_session(db, d["uid"])
        if kind in ("connect", "enter"):
            if row is None:
                db.execute(
                    "INSERT INTO player_sessions(name, uid, address, joined_at, last_seen, maps)"
                    " VALUES (?,?,?,?,?,?)",
                    (d["name"], d["uid"], d.get("address", ""), ts, ts, self.log_map or self.current_map or ""))
            else:
                db.execute("UPDATE player_sessions SET last_seen=MAX(last_seen, ?),"
                           " address=CASE WHEN ?<>'' THEN ? ELSE address END WHERE id=?",
                           (ts, d.get("address", ""), d.get("address", ""), row["id"]))
        elif row is None:
            return
        elif kind in ("disconnect", "kick"):
            db.execute("UPDATE player_sessions SET left_at=?, last_seen=MAX(last_seen, ?) WHERE id=?",
                       (ts, ts, row["id"]))
        elif kind == "rename":
            db.execute("UPDATE player_sessions SET name=?, last_seen=MAX(last_seen, ?) WHERE id=?",
                       (d["new"], ts, row["id"]))
        else:
            if kind == "suicide":
                db.execute("UPDATE player_sessions SET deaths=deaths+1 WHERE id=?", (row["id"],))
            db.execute("UPDATE player_sessions SET last_seen=MAX(last_seen, ?) WHERE id=?", (ts, row["id"]))

    def sessions(self, since=None, limit=2000):
        """Заходы от новых к старым. left_at пуст — игрок ещё на сервере."""
        sql = ("SELECT id, name, address, joined_at, last_seen, left_at, maps, kills, deaths"
               " FROM player_sessions")
        args = []
        if since:
            sql += " WHERE joined_at >= ?"
            args.append(int(since))
        sql += " ORDER BY joined_at DESC LIMIT ?"
        args.append(limit)
        with self._db() as db:
            rows = [dict(r) for r in db.execute(sql, args)]
        for r in rows:
            r["online"] = r["left_at"] is None
            r["duration"] = (r["left_at"] or r["last_seen"]) - r["joined_at"]
            r["maps"] = [m for m in r["maps"].split(",") if m]
        return rows

    def since(self):
        with self._db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='presence_since'").fetchone()
        return int(row["value"]) if row else None
