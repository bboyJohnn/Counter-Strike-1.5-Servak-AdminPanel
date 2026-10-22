#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разбор живого лога в SQLite и выборки для страницы статистики.

Матч — одна карта: от «Log file started» до следующего. В отличие от Quake, в
логе сервера у каждой строки есть дата и время, поэтому время матчей точное.
Сверх убийств Counter-Strike пишет раунды (кто выиграл и как), бомбу, заложников
и убийства своих — они считаются по матчам и по игрокам.
Название карты в логе этой версии нет — оно берётся из таблицы map_starts, которую
пишет live.py (панель спрашивает сервер, какая карта загрузилась). Если панель в
тот момент не работала, карта остаётся «?».

Файл читается по частям: в базе хранится позиция и inode. Позиция указывает на
начало незаконченного матча — он будет дочитан целиком в следующий раз. Когда
live.log вырастает больше 10 МБ, разобранная часть уходит в live.log.1, а
незаконченный матч остаётся в файле (trim) — статистика живёт в базе.
"""

import os
import shutil
import sqlite3
import time

import logline

# Названия оружия в логе Counter-Strike 1.5 → подпись в панели (переводится словарями i18n).
WEAPONS = {
    "knife": "Нож", "glock18": "Glock 18", "usp": "USP", "p228": "P228", "deagle": "Desert Eagle",
    "elite": "Dual Elites", "fiveseven": "Five-SeveN", "m3": "Benelli M3", "xm1014": "Benelli XM1014",
    "mac10": "MAC-10", "tmp": "TMP", "mp5navy": "MP5", "ump45": "UMP 45", "p90": "P90",
    "ak47": "AK-47", "sg552": "SG 552", "m4a1": "M4A1", "aug": "AUG", "scout": "Scout", "awp": "AWP",
    "g3sg1": "G3/SG-1", "sg550": "SG 550", "m249": "M249", "grenade": "Граната",
    "worldspawn": "Падение / мир", "world": "Падение / мир", "trigger_hurt": "Ловушка",
    "env_explosion": "Взрыв", "func_door": "Дверь", "func_door_rotating": "Дверь", "func_train": "Поезд",
    "func_vehicle": "Автомобиль", "tank": "Турель", "func_tank": "Турель",
}
ENVIRONMENT = {"worldspawn", "world", "trigger_hurt", "env_explosion", "func_door",
               "func_door_rotating", "func_train", "func_vehicle", "tank", "func_tank"}
# Действия игроков (строки «triggered»), которые считаются: бомба и заложники
PLAYER_GOALS = {"Planted_The_Bomb": "plants", "Defused_The_Bomb": "defuses", "Rescued_A_Hostage": "rescues"}
# Как закончился раунд (строки «Team … triggered») → счётчик матча
ROUND_ENDS = {"Target_Bombed": "exploded", "Bomb_Defused": "defused"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map TEXT, started_at INTEGER, duration INTEGER,
    humans INTEGER, bots INTEGER, kills INTEGER, seen_at INTEGER,
    rounds INTEGER DEFAULT 0, ct_wins INTEGER DEFAULT 0, t_wins INTEGER DEFAULT 0,
    planted INTEGER DEFAULT 0, exploded INTEGER DEFAULT 0, defused INTEGER DEFAULT 0,
    rescued INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE, is_bot INTEGER,
    matches INTEGER DEFAULT 0, kills INTEGER DEFAULT 0, deaths INTEGER DEFAULT 0,
    suicides INTEGER DEFAULT 0, score_sum INTEGER DEFAULT 0, playtime INTEGER DEFAULT 0,
    last_seen_at INTEGER, teamkills INTEGER DEFAULT 0, plants INTEGER DEFAULT 0,
    defuses INTEGER DEFAULT 0, rescues INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS match_players (
    match_id INTEGER, player_id INTEGER, score INTEGER, kills INTEGER, deaths INTEGER,
    playtime INTEGER,
    PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS weapon_kills (
    player_id INTEGER, weapon TEXT, kills INTEGER,
    PRIMARY KEY (player_id, weapon)
);
CREATE INDEX IF NOT EXISTS mp_player ON match_players(player_id);
CREATE INDEX IF NOT EXISTS m_started ON matches(started_at);
"""

MAX_LOG = 10 * 1024 * 1024
DUP_START = 5  # «Log file started» дважды за 5 секунд без событий — та же карта (server.cfg делает log on)


class Stats:
    def __init__(self, db_path, log_path):
        self.db_path = db_path
        self.log_path = log_path
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(db, key, default=None):
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    @staticmethod
    def _set_meta(db, key, value):
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", (key, str(value)))

    def state(self):
        with self._db() as db:
            return {
                "offset": int(self._meta(db, "stats_offset", 0)),
                "parsed_at": int(self._meta(db, "stats_parsed_at", 0)),
                "matches": db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"],
                "log_size": os.path.getsize(self.log_path) if os.path.exists(self.log_path) else 0,
            }

    # --- разбор -----------------------------------------------------------

    def update(self):
        """Дочитывает лог. Возвращает, сколько матчей добавлено."""
        if not os.path.exists(self.log_path):
            return 0
        st = os.stat(self.log_path)
        inode = "%d:%d" % (st.st_dev, st.st_ino)
        with self._db() as db:
            offset = int(self._meta(db, "stats_offset", 0))
            if self._meta(db, "stats_inode", "") != inode or st.st_size < offset:
                offset = 0
                self._set_meta(db, "stats_inode", inode)
            if st.st_size == offset:
                return 0
            with open(self.log_path, "rb") as f:
                f.seek(offset)
                data = f.read(st.st_size - offset)
            cut = data.rfind(b"\n")
            if cut == -1:
                return 0
            skip_before = int(self._meta(db, "stats_last_flushed", 0))
            added, resume = self._consume(db, data[:cut + 1], skip_before)
            self._set_meta(db, "stats_offset", offset + resume)
            self._set_meta(db, "stats_parsed_at", int(time.time()))
        self._trim()
        return added

    def _trim(self):
        """Лог больше 10 МБ: всё разобранное — в live.log.1, в файле остаётся только
        незаконченный матч. socat пишет в файл с O_APPEND, поэтому после обрезки он
        просто продолжает с нового конца."""
        st = os.stat(self.log_path)
        if st.st_size <= MAX_LOG:
            return
        with self._db() as db:
            offset = int(self._meta(db, "stats_offset", 0))
            if st.st_size - offset > 1024 * 1024:
                return  # незаконченный хвост слишком велик — подождём конца карты
            shutil.copyfile(self.log_path, self.log_path + ".1")
            with open(self.log_path, "r+b") as f:
                f.seek(offset)
                tail = f.read()
                f.seek(0)
                f.truncate()
                f.write(tail)
            self._set_meta(db, "stats_offset", 0)

    def _consume(self, db, data, skip_before):
        """Разбирает целые строки. Возвращает (матчей добавлено, откуда читать дальше).
        «Откуда читать дальше» — начало незаконченного матча."""
        match, match_pos, added, pos = None, len(data), 0, 0
        for raw in data.split(b"\n"):
            line_pos = pos
            pos += len(raw) + 1
            parsed = logline.parse(logline.clean_line(raw))
            if not parsed:
                continue
            ts, kind, d = parsed
            if kind == "map_start":
                if match and not match["events"] and ts - match["start"] <= DUP_START:
                    continue
                if match:
                    if match["start"] > skip_before:
                        self._flush(db, match, ts)
                        added += 1
                match = {"start": ts, "last": ts, "slots": {}, "gone": [], "kills": 0, "events": 0,
                         "rounds": 0, "ct_wins": 0, "t_wins": 0, "planted": 0, "exploded": 0,
                         "defused": 0, "rescued": 0}
                match_pos = line_pos
                continue
            if match is None or kind in ("map_end", "map_name", "other", "say", "world", "team"):
                continue
            match["events"] += 1
            match["last"] = ts
            if kind == "kill":
                v = self._slot(match, d["victim_uid"], d["victim"], d["victim_bot"], ts)
                v["deaths"] += 1
                match["kills"] += 1
                if d["killer_uid"] == d["victim_uid"]:
                    v["suicides"] += 1
                elif d.get("teamkill"):
                    k = self._slot(match, d["killer_uid"], d["killer"], d["killer_bot"], ts)
                    k["teamkills"] += 1
                else:
                    k = self._slot(match, d["killer_uid"], d["killer"], d["killer_bot"], ts)
                    k["kills"] += 1
                    k["weapons"][d["weapon"]] = k["weapons"].get(d["weapon"], 0) + 1
            elif kind == "suicide":
                v = self._slot(match, d["uid"], d["name"], d["bot"], ts)
                v["deaths"] += 1
                v["suicides"] += 1
                match["kills"] += 1
            elif kind in ("connect", "enter"):
                s = self._slot(match, d["uid"], d["name"], d["bot"], ts)
                if s["in"] is None:
                    s["in"] = ts
            elif kind in ("disconnect", "kick"):
                s = match["slots"].pop(d["uid"], None)
                if s:
                    if s["in"] is not None:
                        s["playtime"] += max(0, ts - s["in"])
                        s["in"] = None
                    match["gone"].append(s)
            elif kind == "rename":
                s = match["slots"].get(d["uid"])
                if s:
                    s["name"] = d["new"]
            elif kind == "trigger":
                col = PLAYER_GOALS.get(d["action"])
                if col:
                    s = self._slot(match, d["uid"], d["name"], d["bot"], ts)
                    s[col] += 1
                    if col == "plants":
                        match["planted"] += 1
                    elif col == "rescues":
                        match["rescued"] += 1
            elif kind == "team_win":
                match["rounds"] += 1
                if d["team"] in ("CT", "T"):
                    match["ct_wins" if d["team"] == "CT" else "t_wins"] += 1
                col = ROUND_ENDS.get(d["action"])
                if col:
                    match[col] += 1
        if match is None:
            return added, len(data)
        return added, match_pos  # последний матч ещё идёт

    @staticmethod
    def _slot(match, uid, name, bot, ts):
        s = match["slots"].get(uid)
        if s is None:
            s = match["slots"][uid] = {"name": name, "is_bot": 1 if bot else 0, "kills": 0, "deaths": 0,
                                       "suicides": 0, "playtime": 0, "in": ts, "weapons": {},
                                       "teamkills": 0, "plants": 0, "defuses": 0, "rescues": 0}
        if bot:
            s["is_bot"] = 1
        return s

    @staticmethod
    def _players_of(match, end):
        """Все, кто был в матче. Вышел и вернулся в тот же матч — записи сливаются по имени."""
        merged = {}
        for p in match["gone"] + list(match["slots"].values()):
            if not p["name"]:
                continue
            if p["in"] is not None:
                p["playtime"] += max(0, end - p["in"])
                p["in"] = None
            m = merged.get(p["name"])
            if m is None:
                merged[p["name"]] = p
                continue
            for k in ("kills", "deaths", "suicides", "playtime", "teamkills", "plants", "defuses", "rescues"):
                m[k] += p[k]
            m["is_bot"] = max(m["is_bot"], p["is_bot"])
            for w, n in p["weapons"].items():
                m["weapons"][w] = m["weapons"].get(w, 0) + n
        return merged

    def _flush(self, db, match, end):
        players = self._players_of(match, end)
        humans = sum(1 for p in players.values() if not p["is_bot"])
        row = db.execute("SELECT map FROM map_starts WHERE ts BETWEEN ? AND ? ORDER BY ABS(ts - ?) LIMIT 1",
                         (match["start"] - 10, match["start"] + 120, match["start"])).fetchone()
        cur = db.execute(
            "INSERT INTO matches(map, started_at, duration, humans, bots, kills, seen_at, rounds, ct_wins, t_wins,"
            " planted, exploded, defused, rescued) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["map"] if row else "?", match["start"], max(0, end - match["start"]),
             humans, len(players) - humans, match["kills"], int(time.time()), match["rounds"], match["ct_wins"],
             match["t_wins"], match["planted"], match["exploded"], match["defused"], match["rescued"]))
        match_id = cur.lastrowid
        for p in players.values():
            db.execute("INSERT OR IGNORE INTO players(name, is_bot) VALUES (?,?)", (p["name"], p["is_bot"]))
            pid = db.execute("SELECT id FROM players WHERE name=?", (p["name"],)).fetchone()["id"]
            score = p["kills"] - p["suicides"] - p["teamkills"]   # как в таблице счёта CS
            db.execute(
                "UPDATE players SET is_bot=?, matches=matches+1, kills=kills+?, deaths=deaths+?,"
                " suicides=suicides+?, score_sum=score_sum+?, playtime=playtime+?, last_seen_at=?,"
                " teamkills=teamkills+?, plants=plants+?, defuses=defuses+?, rescues=rescues+? WHERE id=?",
                (p["is_bot"], p["kills"], p["deaths"], p["suicides"], score, p["playtime"], end,
                 p["teamkills"], p["plants"], p["defuses"], p["rescues"], pid))
            db.execute(
                "INSERT OR REPLACE INTO match_players(match_id, player_id, score, kills, deaths, playtime)"
                " VALUES (?,?,?,?,?,?)", (match_id, pid, score, p["kills"], p["deaths"], p["playtime"]))
            for w, n in p["weapons"].items():
                db.execute(
                    "INSERT INTO weapon_kills(player_id, weapon, kills) VALUES (?,?,?)"
                    " ON CONFLICT(player_id, weapon) DO UPDATE SET kills = kills + ?", (pid, w, n, n))
        self._set_meta(db, "stats_last_flushed", match["start"])

    # --- выборки ----------------------------------------------------------

    def totals(self):
        with self._db() as db:
            r = db.execute("SELECT COUNT(*) matches, COALESCE(SUM(kills),0) kills,"
                           " COALESCE(SUM(duration),0) seconds, COALESCE(SUM(rounds),0) rounds,"
                           " COALESCE(SUM(ct_wins),0) ct_wins, COALESCE(SUM(t_wins),0) t_wins,"
                           " COALESCE(SUM(planted),0) planted, COALESCE(SUM(exploded),0) exploded,"
                           " COALESCE(SUM(defused),0) defused, COALESCE(SUM(rescued),0) rescued FROM matches").fetchone()
            tk = db.execute("SELECT COALESCE(SUM(teamkills),0) c FROM players").fetchone()["c"]
            humans = db.execute("SELECT COUNT(*) c FROM players WHERE is_bot=0").fetchone()["c"]
            bots = db.execute("SELECT COUNT(*) c FROM players WHERE is_bot=1").fetchone()["c"]
            hm = db.execute("SELECT COUNT(*) c FROM matches WHERE humans>0").fetchone()["c"]
        out = {"humans": humans, "bots": bots, "matches_with_humans": hm, "teamkills": tk}
        out.update(dict(r))
        return out

    def top(self, is_bot, limit=25):
        with self._db() as db:
            rows = db.execute(
                "SELECT name, matches, kills, deaths, suicides, score_sum, playtime, last_seen_at,"
                " teamkills, plants, defuses, rescues"
                " FROM players WHERE is_bot=? ORDER BY kills DESC, matches DESC LIMIT ?",
                (1 if is_bot else 0, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["kd"] = round(r["kills"] / r["deaths"], 2) if r["deaths"] else float(r["kills"])
            out.append(d)
        return out

    def weapons(self, is_bot=None):
        sql = "SELECT w.weapon, SUM(w.kills) kills FROM weapon_kills w JOIN players p ON p.id=w.player_id"
        args = []
        if is_bot is not None:
            sql += " WHERE p.is_bot=?"
            args.append(1 if is_bot else 0)
        sql += " GROUP BY w.weapon ORDER BY kills DESC"
        with self._db() as db:
            rows = db.execute(sql, args).fetchall()
        return [{"weapon": r["weapon"], "title": WEAPONS.get(r["weapon"], r["weapon"]),
                 "kills": r["kills"], "environment": r["weapon"] in ENVIRONMENT} for r in rows]

    def weapons_for(self, names):
        """Оружие живых игроков с этими никами (статистика ведётся по нику)."""
        if not names:
            return []
        with self._db() as db:
            rows = db.execute(
                "SELECT w.weapon, SUM(w.kills) kills FROM weapon_kills w JOIN players p ON p.id=w.player_id"
                " WHERE p.is_bot=0 AND p.name IN (%s) GROUP BY w.weapon ORDER BY kills DESC"
                % ",".join("?" * len(names)), list(names)).fetchall()
        return [{"weapon": r["weapon"], "title": WEAPONS.get(r["weapon"], r["weapon"]),
                 "kills": r["kills"], "environment": r["weapon"] in ENVIRONMENT} for r in rows]

    def maps_by_names(self, names):
        """Карты ников по игровому логу — для карточки игрока («где играет лучше»).
        [{map, matches, kills, deaths}]. Как и оружие, ведётся по нику."""
        if not names:
            return []
        with self._db() as db:
            rows = db.execute(
                "SELECT m.map, COUNT(*) matches, SUM(mp.kills) kills, SUM(mp.deaths) deaths"
                " FROM match_players mp JOIN players p ON p.id = mp.player_id AND p.is_bot = 0"
                " JOIN matches m ON m.id = mp.match_id WHERE p.name IN (%s) GROUP BY m.map"
                % ",".join("?" * len(names)), list(names)).fetchall()
        return [dict(r) for r in rows]

    def maps(self, limit=40):
        with self._db() as db:
            rows = db.execute(
                "SELECT map, COUNT(*) matches, COALESCE(SUM(kills),0) kills,"
                " CAST(AVG(duration) AS INTEGER) avg_duration,"
                " SUM(CASE WHEN humans>0 THEN 1 ELSE 0 END) with_humans,"
                " COALESCE(SUM(rounds),0) rounds, COALESCE(SUM(ct_wins),0) ct_wins, COALESCE(SUM(t_wins),0) t_wins"
                " FROM matches GROUP BY map ORDER BY matches DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def objectives(self, limit=25):
        """Кто ставит и разминирует бомбу, спасает заложников, убивает своих."""
        with self._db() as db:
            rows = db.execute(
                "SELECT name, is_bot, matches, plants, defuses, rescues, teamkills FROM players"
                " WHERE plants + defuses + rescues + teamkills > 0"
                " ORDER BY plants + defuses + rescues DESC, teamkills, matches DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit=30):
        with self._db() as db:
            rows = db.execute("SELECT id, map, started_at, duration, humans, bots, kills, rounds, ct_wins, t_wins"
                              " FROM matches"
                              " ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def activity(self, tz_offset=0):
        """Матчи по часам суток и дням. tz_offset — смещение браузера в минутах, как у
        JS getTimezoneOffset (Москва = -180): часы по часам пользователя."""
        with self._db() as db:
            rows = db.execute("SELECT started_at t, humans FROM matches WHERE started_at IS NOT NULL").fetchall()
        hours, human_hours, days = [0] * 24, [0] * 24, {}
        for r in rows:
            lt = time.gmtime(r["t"] - tz_offset * 60)
            hours[lt.tm_hour] += 1
            if r["humans"]:
                human_hours[lt.tm_hour] += 1
            key = time.strftime("%Y-%m-%d", lt)
            days[key] = days.get(key, 0) + 1
        return {"hours": hours, "human_hours": human_hours,
                "days": [{"day": k, "matches": v} for k, v in sorted(days.items())][-30:]}
