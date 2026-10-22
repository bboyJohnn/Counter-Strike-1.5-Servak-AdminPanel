#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Контейнер (если есть), машина и логи.

Всё, что панель узнаёт не у самого Half-Life, а у системы. Сервер может работать
в Docker (CONTAINER в .env) или просто процессом — тогда время запуска берётся у
процесса hlds, а перезапуск — командой RESTART_CMD (например, systemctl restart hlds).
Вызовы docker медленные (docker stats думает около двух секунд), поэтому
результат кэшируется на несколько секунд.

Три лога:
  * live    — живой лог (LIVE_LOG): строки приходят сразу, их шлёт сам сервер (logaddress);
  * console — консоль hlds: docker logs или файл CONSOLE_LOG — запуск, загрузка карт, падения;
  * hlds    — последний L*.log самого сервера (пишется кусками, с опозданием).
Во всех трёх пароль rcon вырезается: движок пишет его в лог открытым текстом.
"""

import calendar
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import time

import logline

EVENT_RE = re.compile(r"(?i)restart|crash|segmentation|fatal|core dumped|could not|error")
# имена процесса выделенного сервера: hlds_linux (32 бита), hlds_amd64, hlds_run — обёртка
HLDS_NAMES = ("hlds_linux", "hlds_amd64", "hlds_i686", "hlds_i486", "hlds_l", "hlds")


def _run(args, timeout=30):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()


class System:
    def __init__(self, cfg):
        self.container = cfg.container
        self.restart_cmd = cfg.restart_cmd
        self.console_log = cfg.console_log
        self.live_log = cfg.live_log
        self.logs_dir = cfg.hlds_logs
        self.disk_path = cfg.hl_dir if cfg.hl_dir and os.path.isdir(cfg.hl_dir) else "/"
        self._cache = {}

    def _cached(self, key, ttl, fn):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = fn()
        self._cache[key] = (time.time(), value)
        return value

    # --- контейнер --------------------------------------------------------

    def container_info(self):
        if not self.container:
            return None
        return self._cached("container", 5, self._container_info)

    def _container_info(self):
        if not shutil.which("docker"):
            return {"error": "docker не найден"}
        code, out = _run(["docker", "inspect", self.container])
        if code != 0:
            return {"exists": False, "error": out[:300]}
        d = json.loads(out)[0]
        state = d.get("State", {})
        args = d.get("Args") or []
        start_map = args[args.index("+map") + 1] if "+map" in args and args.index("+map") + 1 < len(args) else ""
        info = {
            "exists": True,
            "status": state.get("Status"),
            "running": state.get("Running"),
            "started_at": state.get("StartedAt"),
            "restarts": d.get("RestartCount", 0),
            "oom_killed": state.get("OOMKilled"),
            "image": d.get("Config", {}).get("Image"),
            "memory_limit": d.get("HostConfig", {}).get("Memory", 0),
            "start_map": start_map,
        }
        if state.get("Running"):
            code, out = _run(["docker", "stats", "--no-stream", "--format",
                              "{{.CPUPerc}}|{{.MemUsage}}|{{.PIDs}}", self.container])
            if code == 0 and "|" in out:
                cpu, mem, pids = out.split("|")
                info.update({"cpu": cpu.strip(), "mem": mem.strip(), "pids": pids.strip()})
        return info

    def started_ts(self):
        """Когда запущен сервер (UTC, секунды) или None: контейнер — по docker,
        без него — по старейшему процессу hlds."""
        if self.container:
            iso = (self.container_info() or {}).get("started_at") or ""
            m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", iso)
            if not m:
                return None
            return calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))
        return self._cached("proc", 10, self._hlds_started)

    @staticmethod
    def _hlds_started():
        """Старт процесса hlds по /proc: starttime в тиках с загрузки машины."""
        try:
            boot = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime "))
            tick = os.sysconf("SC_CLK_TCK")
        except (OSError, StopIteration, ValueError):
            return None
        best = None
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                comm = open("/proc/%s/comm" % pid).read().strip()
                if comm not in HLDS_NAMES:
                    continue
                stat = open("/proc/%s/stat" % pid).read()
                start = int(stat.rsplit(")", 1)[1].split()[19])
            except (OSError, ValueError, IndexError):
                continue
            ts = boot + start // tick
            best = ts if best is None else min(best, ts)
        return best

    def can_restart(self):
        return bool(self.container or self.restart_cmd)

    def container_action(self, action):
        """Перезапуск/остановка/запуск: docker — для контейнера, RESTART_CMD — без него
        (только перезапуск)."""
        if action not in ("restart", "stop", "start"):
            raise ValueError("недопустимое действие")
        if self.container:
            code, out = _run(["docker", action, self.container], timeout=90)
        elif self.restart_cmd and action == "restart":
            code, out = _run(shlex.split(self.restart_cmd), timeout=90)
        else:
            return False, "перезапуск не настроен (CONTAINER или RESTART_CMD в .env)"
        self._cache.pop("container", None)
        self._cache.pop("proc", None)
        return code == 0, out

    # --- машина -----------------------------------------------------------

    def host_info(self):
        return self._cached("host", 5, self._host_info)

    def _host_info(self):
        info = {}
        try:
            info["load"] = open("/proc/loadavg").read().split()[:3]
            mem = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                mem[k] = int(v.split()[0]) * 1024
            info["mem_total"] = mem.get("MemTotal", 0)
            info["mem_available"] = mem.get("MemAvailable", 0)
            info["swap_total"] = mem.get("SwapTotal", 0)
            info["swap_free"] = mem.get("SwapFree", 0)
            info["uptime"] = float(open("/proc/uptime").read().split()[0])
            info["cpus"] = os.cpu_count()
        except OSError:
            pass
        du = shutil.disk_usage(self.disk_path)
        info["disk_total"], info["disk_free"] = du.total, du.free
        return info

    # --- логи -------------------------------------------------------------

    def _hlds_log(self):
        files = sorted(glob.glob(os.path.join(self.logs_dir, "L*.log")), key=os.path.getmtime)
        return files[-1] if files else None

    def _console_source(self):
        if self.container:
            return "docker logs %s" % self.container
        return self.console_log or ""

    def log_files(self):
        out = {}
        for key, path in (("live", self.live_log), ("hlds", self._hlds_log())):
            try:
                st = os.stat(path)
                out[key] = {"path": path, "size": st.st_size, "mtime": int(st.st_mtime)}
            except (OSError, TypeError):
                out[key] = {"path": path or "", "size": 0, "mtime": 0, "missing": True}
        src = self._console_source()
        out["console"] = {"path": src, "size": 0, "mtime": 0, "missing": not src}
        return out

    def _tail_file(self, path, lines, grep):
        if not path or not os.path.exists(path):
            return []
        size = os.path.getsize(path)
        window = 4 * 1024 * 1024 if grep else min(size, 256 * 1024 + lines * 300)
        with open(path, "rb") as f:
            f.seek(max(0, size - window))
            data = f.read()
        rows = data.split(b"\n")
        if size > window:
            rows = rows[1:]  # первая строка обрезана посередине
        return [logline.clean_line(r) for r in rows]

    def tail(self, key, lines=300, grep=""):
        """Последние строки лога. С фильтром ищет в последних 4 МБ файла."""
        if key == "console":
            if self.container:
                code, out = _run(["docker", "logs", "--tail", str(20000 if grep else lines), self.container])
                rows = out.split("\n")
            else:
                rows = self._tail_file(self.console_log, lines, grep)
        else:
            rows = self._tail_file(self.live_log if key == "live" else self._hlds_log(), lines, grep)
        rows = [logline.redact(r) for r in rows if r.strip()]
        if grep:
            needle = grep.lower()
            rows = [r for r in rows if needle in r.lower()]
        return rows[-lines:]

    def server_events(self, limit=8):
        """Падения и перезапуски hlds из консоли (hlds_run пишет туда, когда поднимает
        сервер после падения). Строки лога («L дата: …» — чат, убийства) не смотрим:
        в чате бывает что угодно. Кэш 30 секунд. Нет консоли — пусто."""
        if not self._console_source():
            return []

        def fn():
            rows = [r for r in self.tail("console", 3000) if not r.startswith("L ")]
            return [r for r in rows if EVENT_RE.search(r)][-limit:]
        return self._cached("events", 30, fn)
