#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Страна по IP-адресу — из базы GeoLite2-Country (бесплатная, от MaxMind).

Где лежит база — GEOIP_DB в .env (можно несколько путей через запятую: берётся первый
найденный; например, база, которую обновляет другая программа, и запасная копия).
Читает её модуль maxminddb (pip install maxminddb или системный пакет python3-maxminddb).
Нет базы или модуля — панель просто не показывает страны. Адреса игроков никуда не
отправляются: всё ищется в файле на этом сервере.
"""

import ipaddress
import os
import sys
import time

try:
    import maxminddb
except ImportError:
    sys.path.append("/usr/lib/python3/dist-packages")  # системный пакет, в venv его нет
    try:
        import maxminddb
    except ImportError:
        maxminddb = None

LAN = {"code": "LAN", "name": "локальная сеть"}


class Geo:
    def __init__(self, paths):
        self.paths = tuple(paths)
        self.reader = None
        self.path = None
        self.mtime = 0
        self.checked = 0
        self.cache = {}

    def _reader(self):
        """Открытая база. Раз в час проверяет, не обновился ли файл."""
        if maxminddb is None:
            return None
        if self.reader and time.time() - self.checked < 3600:
            return self.reader
        self.checked = time.time()
        for path in self.paths:
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if self.reader and path == self.path and mtime == self.mtime:
                return self.reader
            try:
                reader = maxminddb.open_database(path)
            except Exception:
                continue
            if self.reader:
                try:
                    self.reader.close()
                except Exception:
                    pass
            self.reader, self.path, self.mtime = reader, path, mtime
            self.cache.clear()
            return reader
        return self.reader

    def country(self, ip):
        """{"code": "RU", "name": "Россия"}; локальный адрес — LAN; неизвестно — None."""
        if not ip:
            return None
        if ip in self.cache:
            return self.cache[ip]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        res = None
        if addr.is_private or addr.is_loopback:
            res = LAN
        else:
            reader = self._reader()
            if reader:
                try:
                    rec = reader.get(ip) or {}
                except Exception:
                    rec = {}
                c = rec.get("country") or rec.get("registered_country") or {}
                if c.get("iso_code"):
                    names = c.get("names") or {}
                    res = {"code": c["iso_code"], "name": names.get("ru") or names.get("en") or c["iso_code"]}
        self.cache[ip] = res
        return res
