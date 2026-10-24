#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Живые игроки по IP-адресам: итоги, карточка игрока, рекорды, страны.

Игрок здесь — IP-адрес: ник может совпасть у разных людей, а один человек может
сменить ник. Поэтому всё считается по адресу, а ники, с которыми заходили с этого
адреса, перечисляются. Источник — заходы из player_sessions (live.py), от новых к
старым; боты туда не попадают.
"""


def ip_of(address):
    """Адрес без порта (в базе бывает и «1.2.3.4», и «1.2.3.4:27005»)."""
    address = (address or "").strip()
    if address.count(":") == 1:
        address = address.split(":")[0]
    return address


def kd(kills, deaths):
    return round(kills / deaths, 2) if deaths else float(kills)


def summarize(sessions, geo):
    """Итоги по каждому IP: ники (первый — последний по времени), заходы, время, У/С."""
    by = {}
    for s in sessions:
        ip = ip_of(s["address"])
        if not ip:
            continue
        p = by.get(ip)
        if p is None:
            p = by[ip] = {"ip": ip, "name": s["name"], "names": [], "visits": 0, "seconds": 0,
                          "kills": 0, "deaths": 0, "first": s["joined_at"], "last": s["joined_at"],
                          "online": False}
        if s["name"] not in p["names"]:
            p["names"].append(s["name"])
        p["visits"] += 1
        p["seconds"] += max(0, s["duration"])
        p["kills"] += s["kills"]
        p["deaths"] += s["deaths"]
        p["first"] = min(p["first"], s["joined_at"])
        p["last"] = max(p["last"], s["left_at"] or s["last_seen"])
        p["online"] = p["online"] or s["online"]
    out = list(by.values())
    for p in out:
        p["country"] = geo.country(p["ip"])
        p["kd"] = kd(p["kills"], p["deaths"])
    out.sort(key=lambda p: (-p["seconds"], -p["visits"]))
    return out


def countries(players):
    """Сколько игроков (адресов) и времени из каждой страны."""
    by = {}
    for p in players:
        c = p["country"] or {"code": "?", "name": "не определить"}
        row = by.setdefault(c["code"], {"code": c["code"], "title": c["name"], "players": 0, "seconds": 0})
        row["players"] += 1
        row["seconds"] += p["seconds"]
    return sorted(by.values(), key=lambda r: (-r["players"], -r["seconds"]))


def records(sessions, players):
    """Рекорды живых игроков: [{title, name, ip, value, at}]."""
    hs = [s for s in sessions if ip_of(s["address"])]
    out = []
    if not hs:
        return out

    def rec(title, s, value, at=None):
        out.append({"title": title, "name": s["name"], "ip": ip_of(s["address"]), "value": value,
                    "at": s["joined_at"] if at is None else at})

    best = max(hs, key=lambda s: (s["kills"], -s["joined_at"]))
    if best["kills"]:
        rec("Больше всего убийств за заход", best, "%d" % best["kills"])
    longest = max(hs, key=lambda s: s["duration"])
    rec("Самый долгий заход", longest, {"duration": longest["duration"]})
    good = [s for s in hs if s["kills"] >= 10]
    if good:
        s = max(good, key=lambda s: kd(s["kills"], s["deaths"]))
        rec("Лучший У/С за заход (от 10 убийств)", s, "%g" % kd(s["kills"], s["deaths"]))
    if players:
        p = max(players, key=lambda p: (p["visits"], p["seconds"]))
        out.append({"title": "Чаще всех заходит", "name": p["name"], "ip": p["ip"],
                    "value": {"times": p["visits"]}, "at": None})
    # больше всего людей одновременно
    events = []
    for s in hs:
        events.append((s["joined_at"], 1))
        events.append(((s["left_at"] or s["last_seen"]), -1))
    events.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0
    peak_at = None
    for ts, d in events:
        cur += d
        if cur > peak:
            peak, peak_at = cur, ts
    if peak:
        out.append({"title": "Больше всего людей сразу", "name": None, "ip": None,
                    "value": "%d" % peak, "at": peak_at})
    return out


def top_killers(players, n=6):
    """Лучшие по убийствам живые игроки (по IP)."""
    rows = sorted((p for p in players if p["kills"]), key=lambda p: (-p["kills"], -p["kd"]))[:n]
    return [{"ip": p["ip"], "name": p["name"], "kills": p["kills"], "deaths": p["deaths"],
             "kd": p["kd"], "country": p["country"]} for p in rows]


def human_maps(sessions, n=8):
    """На каких картах бывают живые игроки: сколько заходов застали карту."""
    by = {}
    for s in sessions:
        if ip_of(s["address"]):
            for m in s["maps"]:
                by[m] = by.get(m, 0) + 1
    return sorted(({"map": m, "visits": v} for m, v in by.items()), key=lambda r: -r["visits"])[:n]


DURATIONS = ((60, "меньше минуты"), (300, "1–5 минут"), (1200, "5–20 минут"),
             (3600, "20–60 минут"), (None, "больше часа"))


def durations(sessions):
    """Сколько длятся заходы живых игроков — по корзинам."""
    counts = [0] * len(DURATIONS)
    for s in sessions:
        if not ip_of(s["address"]):
            continue
        d = max(0, s["duration"])
        for i, (limit, _) in enumerate(DURATIONS):
            if limit is None or d < limit:
                counts[i] += 1
                break
    return [{"title": t, "visits": c} for (_, t), c in zip(DURATIONS, counts)]


def newcomers(players, n=6):
    """Новые игроки: кто впервые зашёл позже всех."""
    rows = sorted(players, key=lambda p: -p["first"])[:n]
    return [{"ip": p["ip"], "name": p["name"], "first": p["first"], "visits": p["visits"],
             "country": p["country"]} for p in rows]


def card(ip, sessions, geo, weapons, all_sessions, players=(), maps_log=()):
    """Карточка игрока по IP: всё про его заходы. weapons и maps_log — оружие и карты
    его ников из статистики игрового лога (stats.weapons_for, stats.maps_by_names);
    players — итоги по всем игрокам (summarize), чтобы назвать место по времени в игре."""
    mine = [s for s in sessions if ip_of(s["address"]) == ip]
    if not mine:
        return None
    names = []
    for s in mine:
        if s["name"] not in names:
            names.append(s["name"])
    seconds = sum(max(0, s["duration"]) for s in mine)
    kills = sum(s["kills"] for s in mine)
    deaths = sum(s["deaths"] for s in mine)
    maps = {}
    for s in mine:
        for m in s["maps"]:
            maps[m] = maps.get(m, 0) + 1
    best = max(mine, key=lambda s: (s["kills"], -s["joined_at"]))
    longest = max(mine, key=lambda s: s["duration"])
    # те же ники, но с других адресов — чтобы не перепутать людей
    others = sorted({ip_of(s["address"]) for s in all_sessions
                     if s["name"] in names and ip_of(s["address"]) not in ("", ip)})
    # убийств в час — только по заходам, где были убийства или смерти: пустые заходы
    # (зашёл и сразу вышел) занижали бы счёт
    fought = [s for s in mine if s["kills"] or s["deaths"]]
    fought_sec = sum(max(0, s["duration"]) for s in fought)
    kph = round(sum(s["kills"] for s in fought) * 3600 / fought_sec, 1) if fought_sec >= 60 else None
    rank = next(({"pos": i + 1, "of": len(players)} for i, p in enumerate(players) if p["ip"] == ip), None)
    # где играет лучше: У/С по картам, где набралось хотя бы 10 убийств и смертей
    map_kd = [dict(r, kills=r["kills"] or 0, deaths=r["deaths"] or 0, kd=kd(r["kills"] or 0, r["deaths"] or 0))
              for r in maps_log if (r["kills"] or 0) + (r["deaths"] or 0) >= 10]
    map_kd.sort(key=lambda r: (-r["kd"], -r["kills"]))
    # лучшие заходы — пять с наибольшим числом убийств
    top = sorted((s for s in mine if s["kills"]), key=lambda s: (-s["kills"], s["deaths"], -s["joined_at"]))[:5]
    return {
        "ip": ip, "name": names[0], "names": names, "country": geo.country(ip),
        "online": any(s["online"] for s in mine),
        "visits": len(mine), "seconds": seconds, "avg": seconds // len(mine),
        "first": min(s["joined_at"] for s in mine),
        "last": max(s["left_at"] or s["last_seen"] for s in mine),
        "kills": kills, "deaths": deaths, "kd": kd(kills, deaths),
        "best": {"kills": best["kills"], "deaths": best["deaths"], "at": best["joined_at"]},
        "longest": {"duration": longest["duration"], "at": longest["joined_at"]},
        "maps": sorted(({"map": m, "visits": n} for m, n in maps.items()), key=lambda r: -r["visits"])[:6],
        "joins": [s["joined_at"] for s in mine],
        "recent": [{"name": s["name"], "joined_at": s["joined_at"], "duration": s["duration"],
                    "kills": s["kills"], "deaths": s["deaths"], "online": s["online"], "maps": s["maps"]}
                   for s in mine[:1000]],
        "weapons": weapons[:6],
        "same_names_from": others,
        # [начало, длительность] всех заходов: дни на сервере и дни недели браузер
        # считает сам — в своём часовом поясе
        "spans": [[s["joined_at"], max(0, s["duration"])] for s in mine],
        "kph": kph,
        "rank": rank,
        "map_kd": map_kd[:6],
        "top": [{"at": s["joined_at"], "kills": s["kills"], "deaths": s["deaths"],
                 "duration": s["duration"], "name": s["name"]} for s in top],
    }
