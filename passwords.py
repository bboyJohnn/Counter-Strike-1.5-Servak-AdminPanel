#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хэш пароля панели. В .env лежит только он (PANEL_PASSWORD_HASH), сам пароль — нигде.

Формат: scrypt$<соль base64>$<хэш base64>, scrypt с n=2^14, r=8, p=1 — модуль hashlib,
без сторонних библиотек. Пишут хэш app.py --init и tools/passwd.py.
"""

import base64
import hashlib
import hmac
import os


def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def check_password(password, stored):
    try:
        _, salt, want = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(want))
    except (ValueError, TypeError):
        return False
