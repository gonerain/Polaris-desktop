"""Instance-private configuration and append-only polling cursors."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self._lock = threading.RLock()
        self.path = self.directory / 'history.sqlite3'
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (cursor INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, identity TEXT NOT NULL, chat TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(kind,identity))')
        os.chmod(self.path, 0o600)

    @contextmanager
    def database(self):
        with self._lock:
            db = sqlite3.connect(self.path)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def configuration(self):
        path = self.directory / 'configuration.json'
        if not path.exists():
            return {'instanceName': '飞书机器人', 'appId': '', 'secret': ''}
        return json.loads(path.read_text(encoding='utf-8'))

    def configure(self, value):
        path = self.directory / 'configuration.json'
        temporary = self.directory / ('.configuration-' + uuid4().hex)
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def append(self, kind, payload):
        value = dict(payload)
        value.setdefault('createdAt', int(time.time() * 1000))
        identity = value.get('messageId') if kind == 'message' else uuid4().hex
        identity = identity or uuid4().hex
        with self.database() as db:
            db.execute('INSERT OR IGNORE INTO records(kind,identity,chat,payload) VALUES(?,?,?,?)',
                       (kind, identity, value.get('chatId', ''), json.dumps(value, ensure_ascii=False)))
            row = db.execute('SELECT cursor FROM records WHERE kind=? AND identity=?', (kind, identity)).fetchone()
        return dict(value, cursor=row[0])

    def read(self, kind='message', after=0, limit=100, chat_id=None):
        query, arguments = 'SELECT cursor,payload FROM records WHERE kind=? AND cursor>?', [kind, after]
        if chat_id:
            query += ' AND chat=?'
            arguments.append(chat_id)
        query += ' ORDER BY cursor LIMIT ?'
        arguments.append(limit)
        with self.database() as db:
            rows = db.execute(query, arguments).fetchall()
        values = [dict(json.loads(payload), cursor=cursor) for cursor, payload in rows]
        return {'items': values, 'nextCursor': rows[-1][0] if rows else after}

    def message(self, message_id):
        with self.database() as db:
            row = db.execute('SELECT payload FROM records WHERE kind=? AND identity=?', ('message', message_id)).fetchone()
        return json.loads(row[0]) if row else None
