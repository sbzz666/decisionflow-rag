import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app import engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('DECISIONFLOW_API_KEY', raising=False)
    with TestClient(create_app(str(tmp_path / 'test.db'))) as c:
        yield c


def setup(client, mode='proactive'):
    sid = client.post('/api/sessions', json={'title': '测试'}).json()['id']
    client.put(f'/api/sessions/{sid}/settings', json={'mode': mode})
    client.post(f'/api/sessions/{sid}/sources', json={
        'title': '原约定', 'text': '原约定预付30%，验收后支付70%尾款。'})
    return sid


def send(client, sid, text='这次希望发货前把货款付清。', kind='speech', rid='one'):
    r = client.post(f'/api/sessions/{sid}/messages', json={
        'text': text, 'kind': kind, 'request_id': rid, 'speaker': '供应商'})
    assert r.status_code == 200, r.text
    return r.json()


def test_payment_change_dedupe_clarification_and_question(client):
    sid = setup(client)
    s = send(client, sid)
    assert len(s['alerts']) == 1
    assert s['alerts'][0]['origin'] == 'offline_rule'
    assert len(s['alerts'][0]['evidence_ids']) == 2
    # Same request ID cannot duplicate an input or notification.
    assert len(send(client, sid)['messages']) == 1
    s = send(client, sid, rid='two')
    assert len(s['alerts']) == 1
    s = send(client, sid, '为什么提醒？', 'question', 'three')
    assert s['messages'][-1]['role'] == 'assistant'
    assert s['messages'][-1]['evidence_ids']
    s = send(client, sid, '不是改合同，仍然验收后付尾款。', rid='four')
    assert s['alerts'][0]['status'] == 'clarified'


@pytest.mark.parametrize('mode,expected', [('record_only', None), ('ask_first', 'pending'), ('proactive', 'active')])
def test_participation_modes(client, mode, expected):
    sid = setup(client, mode)
    s = send(client, sid)
    if expected is None:
        assert s['alerts'] == []
    else:
        assert s['alerts'][0]['status'] == expected
    if expected == 'pending':
        a = s['alerts'][0]
        result = client.post(f'/api/sessions/{sid}/alerts/{a["id"]}/expand').json()
        assert result['alerts'][0]['status'] == 'active'


def test_hypothetical_not_treated_as_actual_change(client):
    sid = setup(client)
    s = send(client, sid, '假如有人要求发货前付清全款，我们怎么考虑？')
    assert not s['alerts']


def test_source_deletion_removes_derived_content_and_session_isolation(client):
    sid = setup(client)
    s = send(client, sid)
    source_id = s['sources'][0]['id']
    s = send(client, sid, '为什么？', 'question', 'two')
    assert s['messages'][-1]['role'] == 'assistant'
    other = client.post('/api/sessions', json={}).json()
    assert not other['sources'] and not other['messages']
    s = client.delete(f'/api/sessions/{sid}/sources/{source_id}').json()
    assert not s['alerts'] and not s['sources']
    assert all(m['role'] != 'assistant' for m in s['messages'])
    assert client.delete(f'/api/sessions/{sid}').status_code == 200
    assert client.get(f'/api/sessions/{sid}').status_code == 404


def test_invalid_input_cross_origin_and_cloud_guard(client):
    sid = setup(client)
    assert client.post(f'/api/sessions/{sid}/messages', json={'text': ' ', 'request_id': 'x'}).status_code == 422
    assert client.put(f'/api/sessions/{sid}/settings', json={'mode': 'proactive', 'cloud': True}).status_code == 400
    assert client.post('/api/sessions', headers={'Origin': 'https://evil.example'}, json={}).status_code == 403
    assert client.get('/api/status', headers={'Host': 'evil.example'}).status_code == 403


def test_websocket_flow_and_restart_persistence(tmp_path):
    path = str(tmp_path / 'persist.db')
    with TestClient(create_app(path)) as c:
        sid = c.post('/api/sessions', json={}).json()['id']
        with c.websocket_connect('/ws/' + sid) as ws:
            assert ws.receive_json()['type'] == 'state'
            ws.send_text('broken')
            assert ws.receive_json()['type'] == 'error'
            ws.send_json({'text': '请帮我分析经营目标', 'kind': 'question', 'request_id': 'q'})
            assert ws.receive_json()['type'] == 'processing'
            state = ws.receive_json()['session']
            assert state['messages'][-1]['role'] == 'assistant'
    with TestClient(create_app(path)) as c:
        assert len(c.get('/api/sessions/' + sid).json()['messages']) == 2


def test_mock_model_orchestration_rejects_fabricated_evidence(client, monkeypatch):
    sid = setup(client)
    monkeypatch.setenv('DECISIONFLOW_API_KEY', 'test-not-a-real-key')
    client.put(f'/api/sessions/{sid}/settings', json={'mode': 'proactive', 'cloud': True})
    fake = AsyncMock(return_value={'findings': [{'kind': 'risk', 'title': '伪造', 'detail': 'x',
           'question': 'x', 'evidence_ids': ['DOES_NOT_EXIST']}]})
    monkeypatch.setattr(engine, 'completion', fake)
    s = send(client, sid)
    assert not s['alerts']
    assert any(t['status'] == 'rejected' for t in s['traces'])
    assert fake.call_count == 2


def test_mock_model_reviewer_and_failure(client, monkeypatch):
    sid = setup(client)
    monkeypatch.setenv('DECISIONFLOW_API_KEY', 'test-not-a-real-key')
    client.put(f'/api/sessions/{sid}/settings', json={'mode': 'proactive', 'cloud': True})

    async def fake(system, payload):
        if '复核结论' in system:
            return {'supported': True}
        return {'findings': [{'kind': 'payment', 'title': '条件变化', 'detail': '需要确认',
               'question': '是否修改？', 'evidence_ids': [payload['current']['id'], payload['sources'][0]['id']]}]}
    monkeypatch.setattr(engine, 'completion', fake)
    s = send(client, sid)
    assert len(s['alerts']) == 1
    assert s['alerts'][0]['origin'] == 'model'
    async def broken(*args):
        raise ValueError('invalid model JSON')
    monkeypatch.setattr(engine, 'completion', broken)
    s = send(client, sid, '有什么建议？', 'question', 'two')
    assert '离线' in s['messages'][-1]['text']
    assert any(t['status'] == 'error' for t in s['traces'])
