#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Все настройки панели — в одном файле .env рядом с app.py (образец — .env.example).

Строка «КЛЮЧ=значение». Значение может ссылаться на ключ выше: ${HL_DIR}/server.cfg.
Текст после « #» — пояснение. Пустое значение = взять по умолчанию (оно показано в
.env.example). Обязательна только папка игры HL_DIR, остальное выводится из неё.
Проверить, что панель всё нашла: python3 app.py --check

Необязательное — без него панель просто прячет соответствующие кнопки:
  CONTAINER   — сервер в Docker: карточка контейнера, перезапуск, консоль (docker logs);
  RESTART_CMD — сервер без Docker: команда перезапуска (например, systemctl restart hlds);
  BOTS_CFG    — jk_botti.cfg: карточка ботов;
  GEOIP_DB    — GeoLite2-Country.mmdb: страны игроков.
"""

import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV_REF = re.compile(r"\$\{(\w+)\}")
ENV_COMMENT = re.compile(r"\s+#.*$")


def load_env(path):
    """Ключи .env по порядку. ${KEY} подставляется из уже прочитанных ключей или окружения."""
    env = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith("#"):
            value = ""                              # «ключ=   # пояснение» — значение пустое
        elif len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = ENV_COMMENT.sub("", value)      # «ключ=значение   # пояснение»
        env[key.strip()] = ENV_REF.sub(lambda m: env.get(m.group(1), os.environ.get(m.group(1), "")), value)
    return env


class Config:
    """Прочитанный .env с умолчаниями. Пути — абсолютные строки (относительные — от папки с .env)."""

    def __init__(self, path=None):
        self.path = Path(os.environ.get("PANEL_ENV") or path or BASE / ".env").resolve()
        self.base = self.path.parent            # от неё считаются относительные пути
        self.env = load_env(self.path) if self.path.exists() else {}
        e = self.get

        # вход в панель
        self.password_hash = e("PANEL_PASSWORD_HASH")
        self.secret = e("PANEL_SECRET")
        self.password_file = self.p(e("PASSWORD_FILE"), self.data_default("panel-password.txt"))

        # сеть
        self.panel_host = e("PANEL_HOST", "127.0.0.1")
        self.panel_port = int(e("PANEL_PORT", "8094"))
        self.allowed_peers = [x.strip() for x in e("PANEL_ALLOWED_PEERS", "127.0.0.1,::1").split(",") if x.strip()]
        self.hl_host = e("HL_HOST", "127.0.0.1")
        self.hl_port = int(e("HL_PORT", "27015"))
        self.public_address = e("PUBLIC_ADDRESS")               # host:port, куда заходят игроки

        # как выглядит
        self.title = e("PANEL_TITLE")                           # пусто — имя сервера (hostname)
        self.hub = e("PANEL_HUB")                               # ссылка «Все панели»: URL или :8089

        # файлы сервера
        self.hl_dir = self.p(e("HL_DIR"), "")
        hd = self.hl_dir or "."
        self.data = self.p(e("PANEL_DATA"), str(self.base / "data"))
        self.server_cfg = self.p(e("SERVER_CFG"), os.path.join(hd, "server.cfg"))
        self.rcon_password = e("RCON_PASSWORD")
        self.rcon_cfg = self.p(e("RCON_CFG"), self.server_cfg)
        self.mapcycle = self.p(e("MAPCYCLE"), os.path.join(hd, "mapcycle.txt"))
        self.mappool = self.p(e("MAPPOOL"), os.path.join(self.data, "mappool.txt"))
        self.maps_dirs = [self.p(x.strip(), "") for x in e("MAPS_DIRS", os.path.join(hd, "maps")).split(",") if x.strip()]
        self.listip = self.p(e("LISTIP_CFG"), os.path.join(hd, "listip.cfg"))
        self.hlds_logs = self.p(e("HLDS_LOGS"), os.path.join(hd, "logs"))

        # живой лог: сервер шлёт строки UDP-пакетами (logaddress), панель дописывает их в файл
        self.live_log = self.p(e("LIVE_LOG"), os.path.join(self.data, "live.log"))
        # ключа нет — слушать по умолчанию; ключ есть, но пустой — не слушать: файл пишет кто-то другой
        self.log_udp = self.env["LOG_UDP"].strip() if "LOG_UDP" in self.env else "127.0.0.1:27500"

        # необязательное
        self.container = e("CONTAINER")
        self.restart_cmd = e("RESTART_CMD")
        self.console_log = self.p(e("CONSOLE_LOG"), "")
        self.bots_cfg = self.p(e("BOTS_CFG"), "")
        self.geoip = [self.p(x.strip(), "") for x in
                      e("GEOIP_DB", os.path.join(self.data, "GeoLite2-Country.mmdb")).split(",") if x.strip()]
        # копии статистики (panel.db): сколько дней хранить, 0 — не делать
        self.backup_days = int(e("BACKUP_DAYS", "0"))
        self.backup_dir = self.p(e("BACKUP_DIR"), os.path.join(self.data, "backups"))

    def get(self, key, default=""):
        v = (self.env.get(key) or "").strip()
        return v if v else default

    def p(self, value, default):
        """Путь: пусто — по умолчанию; относительный — от папки, где лежит .env (обычно папка панели)."""
        value = (value or default or "").strip()
        if not value:
            return ""
        path = Path(value)
        return str(path if path.is_absolute() else (self.base / path).resolve())

    def data_default(self, name):
        return os.path.join(self.p(self.get("PANEL_DATA"), str(self.base / "data")), name)

    def log_udp_addr(self):
        """('127.0.0.1', 27500) или None."""
        if not self.log_udp:
            return None
        host, _, port = self.log_udp.rpartition(":")
        return (host or "127.0.0.1", int(port))

    def features(self):
        """Что есть на этом сервере — от этого зависят кнопки в панели."""
        return {
            "container": bool(self.container),
            "restart": bool(self.container or self.restart_cmd),
            "backups": self.backup_days > 0,
            "bots": bool(self.bots_cfg and os.path.exists(self.bots_cfg)),
            # какие боты: yapb.cfg — YaPB (Counter-Strike), иначе jk_botti (Half-Life)
            "bots_kind": "yapb" if os.path.basename(self.bots_cfg or "").lower().startswith("yapb") else "jk_botti",
            "console": bool(self.container or self.console_log),
        }
