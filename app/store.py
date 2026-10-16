"""Single-user local persistence. Every mutation is serialized by the API session lock."""
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, session):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)',
                       (session['id'], json.dumps(session, ensure_ascii=False)))

    def get(self, sid):
        with self.connect() as db:
            row = db.execute('SELECT body FROM sessions WHERE id=?', (sid,)).fetchone()
        if not row:
            raise KeyError(sid)
        return json.loads(row[0])

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM sessions ORDER BY rowid DESC').fetchall()
        return [{'id': s['id'], 'title': s['title'], 'mode': s['mode']} for s in map(lambda r: json.loads(r[0]), rows)]

    def create(self, title='新的对话'):
        s = dict(id=uuid4().hex, title=title, mode='proactive', cloud=False, version=0,
                 messages=[], sources=[], alerts=[], traces=[], processed={})
        self.save(s)
        return s

    def delete(self, sid):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))
