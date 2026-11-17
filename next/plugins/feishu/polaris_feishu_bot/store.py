"""Instance-private configuration and append-only polling cursors."""
from contextlib import contextmanager
import json
import base64
import os
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4
from polaris_platform.protocol import PlatformError


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self._lock = threading.RLock()
        self.path = self.directory / 'history.sqlite3'
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (cursor INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, identity TEXT NOT NULL, chat TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(kind,identity))')
            db.execute('CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS streams (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
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

    @property
    def attachment_directory(self):
        directory = self.directory / 'attachments'
        directory.mkdir(exist_ok=True, mode=0o700)
        return directory

    @staticmethod
    def attachment_name(name):
        if not isinstance(name, str) or not name.strip() or name in ('.', '..') or '/' in name or chr(92) in name or chr(0) in name:
            raise PlatformError('invalid_params', '附件名称须为不含目录的文件名')
        return name

    def save_attachment(self, data, name):
        name = self.attachment_name(name)
        directory = self.attachment_directory / uuid4().hex
        directory.mkdir(mode=0o700)
        path = directory / name
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        return self.register_attachment(path, name)

    def register_attachment(self, path, name=None):
        path = Path(path).resolve()
        if not path.is_relative_to(self.attachment_directory.resolve()) or not path.is_file():
            raise PlatformError('invalid_attachment', '附件须保存在当前实例的附件目录')
        os.chmod(path, 0o600)
        value = dict(file_id=uuid4().hex, path=str(path), name=self.attachment_name(name or path.name), size=path.stat().st_size)
        with self.database() as db:
            db.execute('INSERT INTO attachments(id,payload) VALUES(?,?)', (value['file_id'], json.dumps(value)))
        return value

    def read_attachment(self, file_id, offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1048576:
            raise PlatformError('invalid_params', 'offset 须非负，limit 须为 1–1048576 字节')
        with self.database() as db:
            row = db.execute('SELECT payload FROM attachments WHERE id=?', (file_id,)).fetchone()
        if row is None:
            raise PlatformError('attachment_missing', '当前实例没有此附件')
        value = json.loads(row[0])
        with open(value['path'], 'rb') as stream:
            stream.seek(offset)
            data = stream.read(limit)
        return dict(data_base64=base64.b64encode(data).decode('ascii'), offset=offset,
            nextOffset=offset + len(data), eof=offset + len(data) >= value['size'], name=value['name'], size=value['size'])

    def save_stream(self, state):
        with self.database() as db:
            db.execute('INSERT OR REPLACE INTO streams(id,payload) VALUES(?,?)', (state['streamId'], json.dumps(state, ensure_ascii=False)))

    def reserve_stream_sequence(self, stream_id):
        with self._lock, self.database() as db:
            row = db.execute('SELECT payload FROM streams WHERE id=?', (stream_id,)).fetchone()
            if row is None:
                raise PlatformError('stream_missing', '当前实例没有此流式卡片')
            state = json.loads(row[0])
            if state['state'] != 'open':
                raise PlatformError('stream_finished', '此卡片已完成流式更新')
            state['sequence'] += 1
            db.execute('UPDATE streams SET payload=? WHERE id=?', (json.dumps(state, ensure_ascii=False), stream_id))
        return state

    def active_streams(self):
        with self.database() as db:
            values = [json.loads(row[0]) for row in db.execute('SELECT payload FROM streams')]
        return [dict(stream_id=v['streamId'], card_id=v['cardId'], message_id=v['messageId'],
                     text=v['text'], title=v['title'], state=v['state'], chatId=v.get('chatId', ''),
                     targetId=v['targetId'], targetType=v['targetType']) for v in values if v['state'] == 'open']

    def update_stream_message(self, state):
        with self.database() as db:
            row = db.execute('SELECT payload FROM records WHERE kind=? AND identity=?', ('message', state['messageId'])).fetchone()
            if row is None:
                raise PlatformError('stream_message_missing', '流式卡片对应的本地消息记录不存在')
            value = json.loads(row[0])
            value.update(text=state['text'], streamId=state['streamId'], streamState=state['state'],
                         content={'card': {'text': state['text'], 'title': state['title']}})
            db.execute('UPDATE records SET payload=?, cursor=(SELECT COALESCE(MAX(cursor),0)+1 FROM records) WHERE kind=? AND identity=?',
                       (json.dumps(value, ensure_ascii=False), 'message', state['messageId']))

    def record_media_key(self, file_id, key, kind):
        with self.database() as db:
            row = db.execute('SELECT payload FROM attachments WHERE id=?', (file_id,)).fetchone()
            value = json.loads(row[0])
            value.update(media_key=key, kind=kind)
            db.execute('UPDATE attachments SET payload=? WHERE id=?', (json.dumps(value), file_id))

    def owns_media_key(self, key, kind):
        with self.database() as db:
            return any(value.get('media_key') == key and value.get('kind') == kind
                       for value in (json.loads(row[0]) for row in db.execute('SELECT payload FROM attachments')))
