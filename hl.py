#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разговор с сервером Half-Life (HLDS) по UDP.

Понимает оба поколения выделенного сервера:
  * WON (HLDS 3.1.1.x, протокол 46) — запросы «info», «players», «rules»;
  * Steam (HLDS из SteamCMD, протокол 48) — A2S_INFO / A2S_PLAYER / A2S_RULES,
    с challenge-ответом «A», как требует нынешний движок.
Какой из двух понимает сервер, панель узнаёт сама при первом ответе и запоминает.
Публичные запросы — те же, что у браузера серверов, в лог сервера они не пишутся:
  * info    — имя, карта, число игроков;
  * players — имена, фраги, время на сервере;
  * rules   — значения настроек (mp_timelimit и прочие).
rcon — команды управления (одинаково у WON и Steam):
  * перед командой нужен вызов «challenge rcon», он выдаёт одноразовое число;
  * старый движок пишет каждую команду в свой лог ВМЕСТЕ С ПАРОЛЕМ («Rcon: "rcon 123
    "пароль" status"»). Поэтому панель зовёт rcon только для действий, а список
    игроков берёт из живого лога и публичных запросов; в разделе «Логи» пароль
    вырезается (logline.redact).
Пароль rcon — RCON_PASSWORD в .env или строка rcon_password из RCON_CFG (по умолчанию
server.cfg). В браузер он не уходит.
"""

import asyncio
import re
import socket
import struct
import time

HEADER = b"\xff\xff\xff\xff"
SPLIT = b"\xfe\xff\xff\xff"

# Строка `rcon status`: # слот "имя" userid uniqueid фраги время пинг потери адрес.
# У ботов uniqueid 0 (или BOT), пинг 0, адреса нет.
STATUS_RE = re.compile(
    r'^#\s*(\d+)\s+"(.*)"\s+(\d+)\s+(\S+)\s+(-?\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s*(\S*)\s*$')
LISTIP_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(.+?)\s*$")


class HLServer:
    """Сервер Half-Life: адрес, пароль rcon и запросы к нему."""

    def __init__(self, host, port, password="", rcon_cfg=""):
        self.host = host
        self.port = port
        self.password = password
        self.rcon_cfg = rcon_cfg
        self.mode = None            # «won» или «steam» — какой протокол понимает сервер

    # --- пароль -----------------------------------------------------------

    def rcon_password(self):
        """RCON_PASSWORD из .env, иначе rcon_password из конфига. Наружу не уходит."""
        if self.password:
            return self.password
        try:
            with open(self.rcon_cfg, encoding="utf-8", errors="replace") as f:
                m = re.search(r'^\s*rcon_password\s+"?([^"\r\n]*)"?', f.read(), re.M)
                return m.group(1).strip() if m else ""
        except (OSError, TypeError):
            return ""

    # --- низкий уровень ---------------------------------------------------

    @staticmethod
    def _join(packets):
        """Склеивает ответ. Большие ответы движок режет на части: заголовок
        FE FF FF FF, номер запроса (4 байта), байт «номер части << 4 | всего частей»."""
        whole, parts = b"", {}
        for p in packets:
            if p.startswith(SPLIT) and len(p) > 9:
                parts[p[8] >> 4] = p[9:]
            else:
                whole += p
        if parts:
            whole = b"".join(parts[i] for i in sorted(parts)) + whole
        return whole

    def _exchange(self, sock, payload, timeout, collect, split_aware=False):
        """Запрос и ответ. split_aware — ответ на публичный запрос: если он пришёл одним
        пакетом, больше не ждём; если частями (FE FF FF FF) — ждём, пока придут все части.
        Иначе (rcon) собираем всё, что придёт за collect секунд: длинный ответ rcon — это
        несколько отдельных пакетов без номеров."""
        sock.settimeout(timeout)
        sock.sendto(HEADER + payload, (self.host, self.port))
        packets = [sock.recvfrom(65535)[0]]
        if split_aware:
            if not packets[0].startswith(SPLIT) or len(packets[0]) < 9:
                return self._join(packets)
            total = packets[0][8] & 0x0F
            deadline = time.time() + max(collect, 1.0)
            while len({p[8] >> 4 for p in packets if p.startswith(SPLIT) and len(p) > 8}) < total \
                    and time.time() < deadline:
                sock.settimeout(max(0.05, deadline - time.time()))
                try:
                    packets.append(sock.recvfrom(65535)[0])
                except socket.timeout:
                    break
            return self._join(packets)
        deadline = time.time() + collect
        while time.time() < deadline:
            sock.settimeout(max(0.05, deadline - time.time()))
            try:
                packets.append(sock.recvfrom(65535)[0])
            except socket.timeout:
                break
        return self._join(packets)

    def _query(self, payload, timeout=2.0, collect=0.15):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            return self._exchange(s, payload, timeout, collect, split_aware=True)
        finally:
            s.close()

    def _a2s(self, payload, want, timeout=2.0, collect=0.15, challenge=True):
        """Запрос Steam: на первый ответ «A» с числом повторить запрос с этим числом."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            raw = self._exchange(s, payload + (HEADER if challenge else b""), timeout, collect, split_aware=True)
            for _ in range(2):
                if raw[4:5] == b"A" and len(raw) >= 9:
                    raw = self._exchange(s, payload + raw[5:9], timeout, collect, split_aware=True)
                else:
                    break
            return raw if raw[4:5] in want else b""
        finally:
            s.close()

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    # --- публичные запросы ------------------------------------------------

    def _info_won(self, timeout):
        raw = self._query(b"info\x00", timeout)
        if not raw.startswith(HEADER + b"C"):
            return None
        body, fields, pos = raw[5:], [], 0
        for _ in range(5):
            end = body.index(b"\x00", pos)
            fields.append(body[pos:end].decode("utf-8", "replace"))
            pos = end + 1
        return {"address": fields[0], "hostname": fields[1], "map": fields[2], "gamedir": fields[3],
                "game": fields[4], "players": body[pos], "maxplayers": body[pos + 1], "protocol": body[pos + 2]}

    def _info_steam(self, timeout):
        raw = self._a2s(b"TSource Engine Query\x00", (b"I", b"m"), timeout, challenge=False)
        if not raw:
            return None
        body, kind = raw[5:], raw[4:5]

        def cstr(pos):
            end = body.index(b"\x00", pos)
            return body[pos:end].decode("utf-8", "replace"), end + 1

        if kind == b"I":                       # нынешний формат: протокол, имя, карта, папка, игра, appid…
            proto, pos = body[0], 1
            name, pos = cstr(pos)
            mapname, pos = cstr(pos)
            folder, pos = cstr(pos)
            game, pos = cstr(pos)
            pos += 2                           # appid
            players, maxp = body[pos], body[pos + 1]
            address = "%s:%s" % (self.host, self.port)
        else:                                  # «m» — старый формат GoldSrc: адрес, имя, карта…
            address, pos = cstr(0)
            name, pos = cstr(pos)
            mapname, pos = cstr(pos)
            folder, pos = cstr(pos)
            game, pos = cstr(pos)
            players, maxp, proto = body[pos], body[pos + 1], body[pos + 2]
        return {"address": address, "hostname": name, "map": mapname, "gamedir": folder,
                "game": game, "players": players, "maxplayers": maxp, "protocol": proto}

    def _info(self):
        """Первый раз пробуем оба протокола и запоминаем ответивший."""
        try:
            if self.mode == "won":
                return self._info_won(2.0)
            if self.mode == "steam":
                return self._info_steam(2.0)
            for mode, fn in (("won", self._info_won), ("steam", self._info_steam)):
                try:
                    info = fn(1.2)
                except (socket.timeout, OSError):
                    info = None
                if info:
                    self.mode = mode
                    return info
        except (socket.timeout, OSError, ValueError, IndexError):
            pass
        return None

    async def info(self):
        """{address, hostname, map, gamedir, game, players, maxplayers, protocol} или None."""
        return await self._run(self._info)

    def _players(self):
        try:
            if self.mode == "steam":
                raw = self._a2s(b"U", (b"D",))
            else:
                raw = self._query(b"players\x00")
        except (socket.timeout, OSError):
            return None
        if not raw.startswith(HEADER + b"D"):
            return None
        body, out = raw[5:], []
        count, pos = body[0], 1
        for _ in range(count):
            pos += 1  # номер в таблице
            end = body.index(b"\x00", pos)
            name = decode_name(body[pos:end])
            frags, seconds = struct.unpack_from("<if", body, end + 1)
            pos = end + 9
            out.append({"name": name, "frags": frags, "time": int(seconds)})
        return out

    async def players(self):
        """[{name, frags, time}] или None, если сервер молчит."""
        if self.mode is None:
            await self.info()
        return await self._run(self._players)

    def _rules(self):
        try:
            if self.mode == "steam":
                raw = self._a2s(b"V", (b"E",), collect=0.4)
            else:
                raw = self._query(b"rules\x00", collect=0.4)
        except (socket.timeout, OSError):
            return {}
        if not raw.startswith(HEADER + b"E"):
            return {}
        items = raw[7:].split(b"\x00")
        return {items[i].decode("latin-1"): items[i + 1].decode("utf-8", "replace")
                for i in range(0, len(items) - 1, 2)}

    async def rules(self):
        """{настройка: значение} — то, что сервер показывает браузеру серверов."""
        if self.mode is None:
            await self.info()
        return await self._run(self._rules)

    # --- rcon -------------------------------------------------------------

    def _rcon(self, command):
        password = self.rcon_password()
        if not password:
            raise RuntimeError("не задан пароль rcon (RCON_PASSWORD или rcon_password в конфиге)")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            ch = self._exchange(s, b"challenge rcon\n", 3.0, 0.0)
            m = re.search(rb"challenge rcon (\d+)", ch)
            if not m:
                raise RuntimeError("сервер не выдал challenge")
            out = self._exchange(s, b'rcon %s "%s" %s\n' % (
                m.group(1), password.encode(), command.encode("utf-8", "replace")), 4.0, 0.6)
        except (socket.timeout, OSError):
            raise RuntimeError("сервер не ответил")
        finally:
            s.close()
        # каждый пакет ответа начинается с FF FF FF FF 'l'
        text = out.replace(HEADER + b"l", b"").replace(b"\x00", b"")
        if text.startswith(b"l"):
            text = text[1:]
        if b"Bad rcon_password" in text:
            raise RuntimeError("сервер не принял пароль rcon")
        return text.decode("utf-8", "replace").strip()

    async def rcon(self, command):
        return await self._run(self._rcon, command)

    async def status(self):
        """Игроки с адресами из `rcon status`. Ботов отличает пустой адрес и пинг 0."""
        rows = []
        for line in (await self.rcon("status")).split("\n"):
            m = STATUS_RE.match(line.strip())
            if m:
                slot, name, uid, unique, frags, tm, ping, loss, addr = m.groups()
                rows.append({"slot": int(slot), "name": name, "userid": int(uid), "uniqueid": unique,
                             "frags": int(frags), "time": tm, "ping": int(ping),
                             "address": addr.split(":")[0] if addr else "", "is_bot": not addr})
        return rows


def decode_name(raw):
    """Имена игроков приходят в той кодировке, в которой их набрали: русские
    клиенты WON — в cp1251, новые — в UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


# Команды сервера и бота jk_botti — для справочника в консоли. Третье поле — нужна
# ли карточка ботов (jk_botti), иначе команда в справочнике не показывается.
COMMANDS = [
    ("status", "игроки: слот, userid, фраги, время, пинг, адрес (у ботов адреса нет)", ""),
    ("users", "живые игроки и их userid", ""),
    ("changelevel <карта>", "сменить карту, игроки остаются на сервере", ""),
    ("map <карта>", "загрузить карту заново (игроки переподключаются)", ""),
    ("say <текст>", "сообщение всем от имени сервера", ""),
    ("kick # <userid>", "выкинуть по userid (номер из status)", ""),
    ("kick <имя>", "выкинуть по имени", ""),
    ("addip <минуты> <ip>", "бан по IP; 0 минут — навсегда. После него — writeip", ""),
    ("removeip <ip>", "снять бан с IP, потом writeip", ""),
    ("listip", "список банов по IP", ""),
    ("writeip", "сохранить баны в listip.cfg (переживают перезапуск)", ""),
    ("jk_botti min_bots <n>", "ботов на сервере не меньше n", "bots"),
    ("jk_botti max_bots <n>", "боты добавляются, пока игроков (с ботами) меньше n", "bots"),
    ("jk_botti botskill <1-5>", "сложность новых ботов: 1 — сильнее всех, 5 — слабее", "bots"),
    ("jk_botti addbot \"\" \"<имя>\" <1-5>", "добавить бота (max_bots может его тут же убрать)", "bots"),
    ("meta list", "плагины Metamod (если он стоит)", ""),
    ("mp_timelimit <минуты>", "время карты до перезапуска сервера (насовсем — в «Настройках сервера»)", ""),
    ("sv_restartround <секунды>", "рестарт игры на этой карте через N секунд: счёт, деньги и оружие — с нуля", ""),
    ("mp_friendlyfire <0|1>", "урон по своим до смены карты (насовсем — в «Настройках сервера»)", ""),
    ("mp_startmoney <800-16000>", "деньги в начале — со следующего рестарта", ""),
    ("hostname <имя>", "имя сервера до перезапуска", ""),
    ("<настройка>", "показать текущее значение, например mp_timelimit", ""),
    ("logaddress", "куда WON-сервер шлёт живой лог (у Steam-сервера — logaddress_list)", ""),
    ("heartbeat", "немедленно отправить анонс мастер-серверам", ""),
    ("exec server.cfg", "перечитать конфиг", ""),
]
