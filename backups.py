"""Копии статистики: база панели (data/panel.db) целиком — матчи, игроки, заходы, журнал действий.

Панель сама делает копию раз в сутки, ещё одну можно сделать кнопкой на вкладке «Бэкап». Хранятся копии
за последние BACKUP_DAYS дней (самая свежая — всегда, даже если она старше). Копия — файл
panel-ГГГГММДД-ЧЧММСС-<вид>.db.gz в BACKUP_DIR, рядом <то же имя>.json: когда сделана, сколько в ней матчей,
игроков и заходов, когда был последний матч — для списка в панели.

Копию можно скачать на компьютер и загрузить обратно (вид upload — «с компьютера»): панель проверяет, что
это целая база панели, и кладёт её в общий список.

Восстановление: сначала копия текущей базы (вид before-restore — её тоже можно вернуть), потом выбранная
копия переписывается в panel.db средствами SQLite (backup API) прямо на работающей панели. Позиции в живом
логе лежат в той же базе, поэтому панель дочитывает лог с места копии: матчи и заходы, сыгранные после неё,
возвращаются, если лог с тех пор не обрезался (панель обрезает его, когда он больше 10 МБ).
"""
import gzip
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time

KINDS = ("auto", "manual", "before-restore", "upload")
NAME_RE = re.compile(r"^panel-(\d{8}-\d{6})-(auto|manual|before-restore|upload)\.db\.gz$")
MAX_UPLOAD = 100 * 1024 * 1024        # копия с компьютера — не больше 100 МБ
# «раз в сутки» с запасом в 10 минут: иначе копия каждый день уезжала бы на час позже (проверка — раз в час)
AUTO_EVERY = 24 * 3600 - 600


class Backups:
    def __init__(self, db_path, folder, days):
        self.db_path = db_path
        self.folder = folder
        self.days = days

    @staticmethod
    def _info_path(path):
        return path[:-len(".db.gz")] + ".json"

    def items(self):
        """Копии, новые сверху: [{name, at, kind, size, matches, players, sessions, last_match}]."""
        try:
            names = os.listdir(self.folder)
        except OSError:
            return []
        out = []
        for name in names:
            m = NAME_RE.match(name)
            if not m:
                continue
            path = os.path.join(self.folder, name)
            try:
                with open(self._info_path(path), encoding="utf-8") as f:
                    info = json.load(f)
            except (OSError, ValueError):
                info = {}
            at = info.get("at") or time.mktime(time.strptime(m.group(1), "%Y%m%d-%H%M%S"))
            st = os.stat(path)
            # копии одной секунды (вручную и сразу «перед восстановлением») — по времени файла
            out.append(((int(at), st.st_mtime), {
                "name": name, "at": int(at), "kind": m.group(2), "size": st.st_size,
                "matches": info.get("matches"), "players": info.get("players"), "sessions": info.get("sessions"),
                "last_match": info.get("last_match")}))
        out.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in out]

    def due(self, now=None):
        """Пора ли делать ежедневную копию."""
        last = [x["at"] for x in self.items() if x["kind"] == "auto"]
        return not last or (now or time.time()) - max(last) >= AUTO_EVERY

    @staticmethod
    def _counts(db):
        def count(table):
            try:
                return db.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            except sqlite3.Error:
                return None
        try:
            last = db.execute("SELECT MAX(started_at) FROM matches").fetchone()[0]
        except sqlite3.Error:
            last = None
        return {"matches": count("matches"), "players": count("players"), "sessions": count("player_sessions"),
                "last_match": last}

    def _tmp(self):
        os.makedirs(self.folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=self.folder)
        os.close(fd)
        return tmp

    def _save(self, db_file, kind):
        """Сжать готовую базу db_file в новую копию вида kind. Возвращает её строку из items()."""
        now = int(time.time())
        while True:
            name = "panel-%s-%s.db.gz" % (time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), kind)
            path = os.path.join(self.folder, name)
            if not os.path.exists(path):
                break
            now += 1
        con = sqlite3.connect(db_file)
        try:
            info = self._counts(con)
        finally:
            con.close()
        try:
            with open(db_file, "rb") as f, gzip.open(path + ".part", "wb", compresslevel=6) as g:
                shutil.copyfileobj(f, g)
            os.replace(path + ".part", path)
        finally:
            if os.path.exists(path + ".part"):
                os.remove(path + ".part")
        info.update(at=now, kind=kind)
        with open(self._info_path(path), "w", encoding="utf-8") as f:
            json.dump(info, f)
        self.prune(now)
        return next(x for x in self.items() if x["name"] == name)

    def create(self, kind="manual"):
        """Сделать копию базы. Возвращает её строку из items()."""
        if kind not in KINDS:
            raise ValueError(kind)
        tmp = self._tmp()
        try:
            # backup API: целая и согласованная копия, даже если панель в это время пишет в базу
            src = sqlite3.connect(self.db_path, timeout=30)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return self._save(tmp, kind)
        finally:
            os.remove(tmp)

    def add(self, upload):
        """Копия с компьютера (файл .db.gz или .db): проверить и положить в список. Возвращает её строку."""
        tmp = self._tmp()
        try:
            self._unpack(upload, tmp)
            return self._save(tmp, "upload")
        finally:
            os.remove(tmp)

    def path_of(self, name):
        """Путь к файлу копии name — только из списка, чужие пути не пройдут."""
        if not any(x["name"] == name for x in self.items()):
            raise LookupError("нет такой копии: %s" % name)
        return os.path.join(self.folder, name)

    @staticmethod
    def _unpack(src, dst):
        """Распаковать копию (gzip или просто база) в dst и проверить, что это целая база панели."""
        try:
            with open(src, "rb") as f:
                packed = f.read(2) == b"\x1f\x8b"
            with (gzip.open if packed else open)(src, "rb") as g, open(dst, "wb") as f:
                shutil.copyfileobj(g, f)
            con = sqlite3.connect(dst)
            try:
                check = con.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
        except (OSError, EOFError, sqlite3.DatabaseError) as e:
            raise ValueError("копия не читается: %s" % e)
        if check != "ok":
            raise ValueError("копия повреждена: %s" % check)
        if not {"meta", "matches"} <= tables:
            raise ValueError("в копии нет статистики панели")

    def prune(self, now=None):
        """Убрать копии старше BACKUP_DAYS дней; самая свежая остаётся всегда."""
        now = now or time.time()
        for x in self.items()[1:]:
            if now - x["at"] > self.days * 86400:
                path = os.path.join(self.folder, x["name"])
                for p in (path, self._info_path(path)):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def restore(self, name):
        """Вернуть базу из копии name. Возвращает (эта копия, копия текущей базы, сделанная перед этим)."""
        chosen = next((x for x in self.items() if x["name"] == name), None)
        if not chosen:
            raise LookupError("нет такой копии: %s" % name)
        tmp = self._tmp()
        try:
            self._unpack(self.path_of(name), tmp)
            before = self.create("before-restore")
            src = sqlite3.connect(tmp)
            dst = sqlite3.connect(self.db_path, timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        finally:
            os.remove(tmp)
        return chosen, before
