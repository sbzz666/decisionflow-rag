import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from .engine import cloud_available, process, trace
from .store import Store
from .rag import index_sources

ROOT = Path(__file__).resolve().parents[1]


class SessionCreate(BaseModel):
    title: str = Field(default='新的对话', min_length=1, max_length=100)


class SourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)
    sensitivity: Literal['internal', 'confidential'] = 'internal'


class Settings(BaseModel):
    mode: Literal['record_only', 'ask_first', 'proactive']
    cloud: bool = False


class Message(BaseModel):
    request_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6000)
    kind: Literal['speech', 'question'] = 'speech'
    speaker: str = Field(default='我', min_length=1, max_length=60)


def create_app(db_path=None):
    app = FastAPI(title='DecisionFlow RAG · FastAPI + React + BM25', version='0.2.0')
    store = Store(db_path or os.getenv('DECISIONFLOW_DB', str(ROOT / 'data' / 'decisionflow.db')))
    locks = {}

    def lock(sid):
        return locks.setdefault(sid, asyncio.Lock())

    def get(sid):
        try:
            session = store.get(sid)
            index_sources(session)
            return session
        except KeyError:
            raise HTTPException(404, '会话不存在')

    # This first release is explicitly local-only, including Host/Origin checks.
    def local_host(host):
        return host.split(':')[0] in ('127.0.0.1', 'localhost', 'testserver')

    def origin_allowed(origin):
        from urllib.parse import urlparse
        return not origin or urlparse(origin).hostname in ('127.0.0.1', 'localhost', 'testserver')

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if not local_host(request.headers.get('host', '')) or not origin_allowed(request.headers.get('origin')):
            return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '拒绝跨站请求'}, status_code=403)
        return await call_next(request)

    @app.get('/api/status')
    async def status():
        return {'model_available': cloud_available(), 'model': os.getenv('DECISIONFLOW_MODEL', 'deepseek-chat'),
                'retrieval': 'chunk_bm25', 'notification': 'in_app_only', 'version': '0.2.0'}

    @app.get('/api/sessions')
    async def sessions():
        return store.list()

    @app.post('/api/sessions')
    async def new_session(body: SessionCreate):
        return store.create(body.title)

    @app.get('/api/sessions/{sid}')
    async def session(sid: str):
        return get(sid)

    @app.delete('/api/sessions/{sid}')
    async def delete(sid: str):
        async with lock(sid):
            get(sid)
            store.delete(sid)
        return {'deleted': True}

    @app.put('/api/sessions/{sid}/settings')
    async def settings(sid: str, body: Settings):
        async with lock(sid):
            s = get(sid)
            if body.cloud and not cloud_available():
                raise HTTPException(400, '服务端未配置模型密钥')
            s.update(body.model_dump())
            store.save(s)
            return s

    @app.post('/api/sessions/{sid}/sources')
    async def source(sid: str, body: SourceCreate):
        from uuid import uuid4
        async with lock(sid):
            s = get(sid)
            if len(s['sources']) >= 50:
                raise HTTPException(400, '单会话最多50条资料')
            if not body.title.strip() or not body.text.strip():
                raise HTTPException(422, '资料名称和内容不能为空')
            s['sources'].append(dict(id='D' + uuid4().hex[:10], **body.model_dump()))
            index_sources(s)
            store.save(s)
            return s

    @app.delete('/api/sessions/{sid}/sources/{source_id}')
    async def delete_source(sid: str, source_id: str):
        async with lock(sid):
            s = get(sid)
            removed = {source_id} | {c['id'] for c in index_sources(s) if c['source_id'] == source_id}
            s['sources'] = [d for d in s['sources'] if d['id'] != source_id]
            index_sources(s)
            # Remove derived alert content as well as dependent assistant answers.
            s['alerts'] = [a for a in s['alerts'] if not removed.intersection(a['evidence_ids'])]
            s['messages'] = [m for m in s['messages'] if not removed.intersection(m.get('evidence_ids', []))]
            store.save(s)
            return s

    @app.post('/api/sessions/{sid}/alerts/{aid}/expand')
    async def expand(sid: str, aid: str):
        async with lock(sid):
            s = get(sid)
            a = next((a for a in s['alerts'] if a['id'] == aid), None)
            if not a:
                raise HTTPException(404, '提醒不存在')
            if a['status'] == 'pending':
                a['status'] = 'active'
                trace(s, '介入控制', '用户确认展开提醒')
                store.save(s)
            return s

    async def submit(sid, body):
        async with lock(sid):
            s = get(sid)
            if body.request_id in s['processed']:
                return s
            if len(s['messages']) >= 500:
                raise HTTPException(400, '会话已达500条，请新建会话')
            await process(s, body.text.strip(), body.kind, body.speaker)
            s['processed'][body.request_id] = True
            store.save(s)
            return s

    @app.post('/api/sessions/{sid}/messages')
    async def message(sid: str, body: Message):
        if not body.text.strip():
            raise HTTPException(422, '内容不能为空')
        return await submit(sid, body)

    @app.websocket('/ws/{sid}')
    async def websocket(ws: WebSocket, sid: str):
        if not local_host(ws.headers.get('host', '')) or not origin_allowed(ws.headers.get('origin')):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            get(sid)
            await ws.send_json({'type': 'state', 'session': get(sid)})
            while True:
                raw = await ws.receive_text()
                if len(raw) > 40000:
                    await ws.send_json({'type': 'error', 'message': '消息过大'})
                    continue
                try:
                    body = Message.model_validate_json(raw)
                    if not body.text.strip():
                        raise ValueError('empty')
                    await ws.send_json({'type': 'processing', 'request_id': body.request_id})
                    s = await submit(sid, body)
                    await ws.send_json({'type': 'state', 'session': s})
                except (ValidationError, ValueError):
                    await ws.send_json({'type': 'error', 'message': '消息格式错误'})
                except HTTPException as e:
                    await ws.send_json({'type': 'error', 'message': str(e.detail)})
        except (WebSocketDisconnect, HTTPException):
            pass

    dist = ROOT / 'frontend' / 'dist'
    if (dist / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/')
    async def index():
        if not (dist / 'index.html').exists():
            return JSONResponse({'detail': '请先构建前端，参见 README'}, status_code=503)
        return FileResponse(dist / 'index.html')

    return app


app = create_app()
