#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Порядок карт (MAPPOOL) и список для движка (MAPCYCLE = mapcycle.txt сервера).

Порядок карт — свой файл панели, по карте в строке, сверху вниз; сервер играет их по
кругу, после последней снова первая:
    crossfire
    -bounce         — минус в начале: карта выключена, сервер её не ставит
    # ...           — комментарий
Его пишет панель (раздел «Карты»); первый раз, пока файла нет, порядок берётся из
нынешнего mapcycle.txt сервера.

Как движок читает список. Игровая библиотека загружает mapcycle.txt при первой смене
карты, дальше идёт по нему по кругу и перечитывает файл, только если в настройке
mapcyclefile сменилось имя. Поэтому панель после записи переключает имя между
"mapcycle.txt" и "./mapcycle.txt" (это один и тот же файл) — и на ближайшей смене
карты сервер берёт ПЕРВУЮ карту нового списка. Отсюда правило: список всегда пишется
повёрнутым так, чтобы первой в нём шла карта после текущей.

Весь mapcycle.txt сервер отправляет каждому входящему игроку, а клиент WON 1.1.1.0
читает только ~8 КБ — с длинным списком игра вылетает при входе («UserMsg: Not Present
on Client»). Список из включённых карт по одной — далеко от этого предела.

mapcycle.txt пишется на месте (тот же inode): если он примонтирован в контейнер
отдельным файлом, замену через rename работающий сервер не увидел бы.
"""

import os


def read_pool(path):
    """[(карта, включена)] по порядку из файла порядка карт."""
    maps, seen = [], set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(("#", "//")) or line.lower().startswith("mode "):
                continue
            on = not line.startswith("-")
            name = line.lstrip("-").split()[0].lower() if line.lstrip("-").strip() else ""
            if name and name not in seen:
                seen.add(name)
                maps.append((name, on))
    return maps


def read_cycle(path):
    """Карты из mapcycle.txt сервера (первое слово строки; у карты бывают условия в кавычках)."""
    out, seen = [], set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith(("//", "#")):
                    continue
                name = line.split()[0].strip('"').lower()
                if name and name not in seen:
                    seen.add(name)
                    out.append(name)
    except OSError:
        pass
    return out


def rotate_after(seq, after):
    """Повернуть круг так, чтобы первой шла карта после after (если она в круге)."""
    if after in seq:
        i = seq.index(after)
        return seq[i + 1:] + seq[:i + 1]
    return list(seq)


def build(maps, after=None):
    """Список для mapcycle.txt: его первая карта — следующая после after."""
    on = [m for m, enabled in maps if enabled]
    if not on:
        raise ValueError("нет ни одной включённой карты")
    if after is None:
        # старт сервера: он встаёт на первую карту, дальше — вторая
        return on[1:] + on[:1]
    return rotate_after(on, after)


def write_cycle(seq, path):
    """«w» обрезает существующий файл, а не создаёт новый: inode тот же."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(seq) + "\n")


def exists(path):
    return bool(path) and os.path.exists(path)
