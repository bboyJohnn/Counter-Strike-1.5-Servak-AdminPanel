#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Журнал действий панели: кто и что менял.

Пишется в ту же базу, что и статистика. Нужен, чтобы через неделю можно было
понять, почему настройка стала другой.
"""

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      INTEGER NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT '',
    ok      INTEGER NOT NULL DEFAULT 1,
    output  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_at ON audit(at DESC);
"""


class Audit:
    def __init__(self, db_path):
        self.db_path = db_path
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def log(self, action, detail="", ok=True, output=""):
        with self._db() as db:
            db.execute(
                "INSERT INTO audit(at, action, detail, ok, output) VALUES (?,?,?,?,?)",
                (int(time.time()), action, detail, 1 if ok else 0, (output or "")[:2000]),
            )

    def recent(self, limit=200):
        with self._db() as db:
            rows = db.execute(
                "SELECT at, action, detail, ok, output FROM audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
