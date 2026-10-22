#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чтение и правка настроек: server.cfg, jk_botti.cfg и карты сервера.

Файлы правятся построчно: панель меняет значение в существующей строке и не
трогает ни комментарии, ни порядок, ни оформление. Перед каждой записью
сохраняется копия в data/cfg-backups. Файл пишется на месте — владелец и права
не меняются (сервер может читать его от другого пользователя).

server.cfg. Разделы страницы «Настройки» — строки-заголовки «// 1. Название»; если
их в файле нет, все настройки идут одним разделом. Пояснение к настройке — текст
после «//» в той же строке.

Карты. Порядок и выключенные карты — свой файл панели (MAPPOOL); список для движка,
mapcycle.txt, строит mapcycle.py. Как движок читает список и почему первой в нём
идёт следующая карта — в описании mapcycle.py.
"""

import os
import re
import shutil
import time

import mapcycle

# Строка настройки server.cfg: ИМЯ ЗНАЧЕНИЕ [// комментарий]
SETTING_RE = re.compile(r'^(?P<head>\s*)(?P<name>[A-Za-z_]\w*)\s+(?P<value>"[^"]*"|[^\s/]+)(?P<tail>.*)$')
# Это команды, а не настройки: их панель не показывает и не правит.
NOT_SETTINGS = {"exec", "log", "logaddress", "logaddress_add", "logaddress_del", "logaddress_delall",
                "map", "changelevel", "echo", "say", "alias", "addip", "removeip", "writeip", "kick", "banid",
                "heartbeat", "rcon_password", "mapcyclefile", "plugin_load", "setmaster", "sv_logfile"}

SECRETS = {"sv_password", "rcon_password"}

# Что применяется не сразу. Остальное панель отправляет серверу по rcon сразу же.
RESTART_ONLY = {
    "sv_voiceenable": "применяется после смены карты",
}

# Настройки ботов в jk_botti.cfg: «имя значение» в начале строки. Применяются по rcon
# командой «jk_botti имя значение».
BOT_SETTINGS = {
    "min_bots": "ботов на сервере не меньше этого числа",
    "max_bots": "боты добавляются, пока игроков вместе с ботами меньше этого числа; "
                "зашёл живой игрок — один бот уходит",
    "botskill": "сложность новых ботов: 1 — сильнее всех, 5 — слабее",
    "bot_chat_percent": "как часто боты болтают в чате, % (раз в 30 с)",
    "bot_taunt_percent": "как часто дразнят после убийства, %",
    "bot_whine_percent": "как часто жалуются после смерти, %",
    "bot_logo_percent": "как часто рисуют спреи, %",
    "random_color": "случайные цвета моделей ботов: 1 — да",
}
BOT_LINE_RE = re.compile(r"^(?P<head>\s*)(?P<off>#?)(?P<name>[a-z_]+)(?P<sp>\s+)(?P<value>\S+)(?P<tail>.*)$")


class Files:
    """Общее для всех правок: копии, запись с сохранением владельца."""

    def __init__(self, backup_dir):
        self.backup_dir = backup_dir

    def backup(self, path):
        """Копия файла перед записью. Файла ещё нет — копировать нечего, вернёт «»."""
        if not os.path.exists(path):
            return ""
        os.makedirs(self.backup_dir, exist_ok=True)
        now = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-%03d" % (now % 1 * 1000)
        dst = os.path.join(self.backup_dir, os.path.basename(path) + "." + stamp)
        shutil.copy2(path, dst)
        self._trim(os.path.basename(path))
        return dst

    def _trim(self, prefix, keep=30):
        files = sorted((f for f in os.listdir(self.backup_dir) if f.startswith(prefix + ".")), reverse=True)
        for old in files[keep:]:
            try:
                os.remove(os.path.join(self.backup_dir, old))
            except OSError:
                pass

    def list_backups(self):
        if not os.path.isdir(self.backup_dir):
            return []
        return sorted(os.listdir(self.backup_dir), key=lambda f: f.rsplit(".", 1)[-1], reverse=True)[:40]

    @staticmethod
    def write(path, text):
        """Пишет в тот же файл (тот же inode) — владелец и права не меняются.

        Не через временный файл и rename: server.cfg, mapcycle.txt и другие примонтированы
        в контейнер отдельными файлами, и работающий сервер видел бы старый файл до
        перезапуска контейнера. А server.cfg сервер выполняет на каждой смене карты —
        и откатывал бы настройку, которую панель только что применила по rcon (так
        04.10.2026 «не работал» mp_fraglimit). Копию перед записью делает backup().
        Файла ещё нет (первое сохранение порядка карт) — создаёт."""
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return
        with open(path, "r+", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())


class ServerConfig:
    def __init__(self, path, files):
        self.path = path
        self.files = files

    def read(self):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def settings(self, hide_secrets=True):
        """Все настройки файла в порядке появления, с разделами «// N. Название».
        Нет таких заголовков — один раздел на весь файл."""
        text = self.read()
        sectioned = re.search(r"^\s*//\s*\d+\.", text, re.M)
        out, section = [], "" if sectioned else "server.cfg"
        for n, line in enumerate(text.split("\n")):
            head = re.match(r"^\s*//\s*(\d+\..*)$", line)
            if head:
                section = head.group(1).strip()
                continue
            if sectioned and re.match(r"^\s*//\s*(Служебное|Service)", line):
                section = ""
            m = SETTING_RE.match(line)
            if not m or line.lstrip().startswith("//") or not section:
                continue
            name = m.group("name")
            if name.lower() in NOT_SETTINGS:
                continue
            tail = m.group("tail")
            secret = name.lower() in SECRETS
            out.append({
                "line": n,
                "name": name,
                "value": "" if (secret and hide_secrets) else m.group("value").strip('"'),
                "secret": secret,
                "comment": tail.split("//", 1)[1].strip() if "//" in tail else "",
                "section": section,
                "restart_note": RESTART_ONLY.get(name.lower(), ""),
            })
        return out

    def set_value(self, name, value):
        """Меняет одну настройку. Возвращает (старое, новое, путь_к_копии)."""
        if '"' in value or "\n" in value:
            raise ValueError("значение не должно содержать кавычек и переводов строк")
        lines = self.read().split("\n")
        for i, line in enumerate(lines):
            m = SETTING_RE.match(line)
            if not m or line.lstrip().startswith("//") or m.group("name").lower() != name.lower():
                continue
            old = m.group("value").strip('"')
            quoted = m.group("value").startswith('"') or not value or re.search(r"\s", value)
            shown = '"%s"' % value if quoted else value
            # выравнивание комментария сохраняем, насколько позволяет длина значения
            tail = m.group("tail")
            pad = len(m.group("value")) - len(shown)
            if tail.startswith(" ") and pad != 0:
                tail = " " * max(1, len(tail) - len(tail.lstrip(" ")) + pad) + tail.lstrip(" ")
            lines[i] = "%s%s %s%s" % (m.group("head"), m.group("name"), shown, tail)
            backup = self.files.backup(self.path)
            self.files.write(self.path, "\n".join(lines))
            return old, value, backup
        raise KeyError("в server.cfg нет настройки %s" % name)


class BotConfig:
    def __init__(self, path, files):
        self.path = path
        self.files = files

    def read(self):
        with open(self.path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def settings(self):
        """Настройки из BOT_SETTINGS: последняя незакомментированная строка каждой."""
        found = {}
        for line in self.read().split("\n"):
            m = BOT_LINE_RE.match(line)
            if m and not m.group("off") and m.group("name") in BOT_SETTINGS:
                found[m.group("name")] = m.group("value")
        return [{"name": k, "value": found.get(k, ""), "comment": v, "section": "Боты (jk_botti.cfg)",
                 "secret": False, "restart_note": "", "bot": True} for k, v in BOT_SETTINGS.items()]

    def set_value(self, name, value):
        if name not in BOT_SETTINGS:
            raise KeyError("нет такой настройки ботов: %s" % name)
        if not re.fullmatch(r"\d{1,3}", value):
            raise ValueError("нужно целое число")
        lines = self.read().split("\n")
        idx = None
        for i, line in enumerate(lines):
            m = BOT_LINE_RE.match(line)
            if m and not m.group("off") and m.group("name") == name:
                idx = i
        if idx is None:
            # настройки нет или она закомментирована — дописываем перед первым addbot
            at = next((i for i, l in enumerate(lines) if re.match(r"^#?addbot", l)), len(lines))
            lines.insert(at, "%s %s" % (name, value))
            old = ""
        else:
            m = BOT_LINE_RE.match(lines[idx])
            old = m.group("value")
            lines[idx] = "%s%s%s%s%s" % (m.group("head"), name, m.group("sp"), value, m.group("tail"))
        backup = self.files.backup(self.path)
        self.files.write(self.path, "\n".join(lines))
        return old, value, backup


class MapPool:
    """Карты сервера: порядок и выключенные (MAPPOOL) и список для движка (MAPCYCLE)."""

    HEADER = ("# Карты сервера Half-Life — порядок сверху вниз. Пишет веб-панель (раздел «Карты»),\n"
              "# можно править и руками: тогда список заработает после перезапуска сервера.\n"
              "# После последней карты — снова первая. Карта с минусом в начале выключена: -bounce\n")

    def __init__(self, pool_path, cycle_path, maps_dirs, files):
        self.pool_path = pool_path
        self.cycle_path = cycle_path
        self.maps_dirs = list(maps_dirs)
        self.files = files

    def available(self):
        """Карты, которые есть на сервере: *.bsp во всех папках MAPS_DIRS."""
        out = set()
        for d in self.maps_dirs:
            try:
                out.update(f[:-4].lower() for f in os.listdir(d) if f.lower().endswith(".bsp"))
            except OSError:
                pass
        return sorted(out)

    def read(self):
        """[(карта, включена)] по порядку. Своего файла ещё нет — порядок из нынешнего
        mapcycle.txt сервера, а нет и его — все карты сервера по алфавиту."""
        if mapcycle.exists(self.pool_path):
            return mapcycle.read_pool(self.pool_path)
        maps = mapcycle.read_cycle(self.cycle_path) or self.available()
        return [(m, True) for m in maps]

    def order(self):
        """Все карты сервера по порядку. Карты, которых в порядке нет
        (например, новые), стоят в конце выключенными."""
        maps = self.read()
        have = {m for m, _ in maps}
        maps += [(m, False) for m in self.available() if m not in have]
        return [{"name": m, "on": on} for m, on in maps]

    def pool(self):
        """Включённые карты по порядку."""
        return [m for m, on in self.read() if on]

    def set_order(self, maps):
        """maps — [(карта, включена)]. Копия старого файла — в data/cfg-backups."""
        lines = [self.HEADER.rstrip("\n")] + [("" if on else "-") + m for m, on in maps]
        backup = self.files.backup(self.pool_path)
        self.files.write(self.pool_path, "\n".join(lines) + "\n")
        return backup

    def regenerate(self, after=None):
        """Переписать mapcycle.txt (на месте) так, чтобы первой шла карта после after.
        Возвращает новый список. Своего файла порядка ещё нет — сначала он записывается
        из нынешнего mapcycle.txt: иначе после поворота списка порядок начинался бы не с той карты."""
        if not mapcycle.exists(self.pool_path):
            self.set_order(self.read())
        try:
            seq = mapcycle.build(self.read(), (after or "").lower() or None)
        except ValueError as e:
            raise RuntimeError(str(e))
        mapcycle.write_cycle(seq, self.cycle_path)
        return seq

    def restart_list(self, start_map=None):
        """Для перезапуска сервера: он встанет на start_map (+map в его командной строке),
        дальше пойдёт по новому списку."""
        return self.regenerate(start_map)

    @staticmethod
    def following(order, current, n=10):
        """Следующие n карт по кругу после current (или с начала, если её в круге нет)."""
        if not order:
            return []
        i = order.index(current) + 1 if current in order else 0
        return [order[(i + k) % len(order)] for k in range(n)]
