from unittest.mock import AsyncMock

from app.rag import chunks, retrieve
from app import engine
from test_flow import client, setup, send


def test_chunk_offsets_coverage_and_revision():
    source = dict(id='D1', title='合同', text=('交付约定。' * 220), sensitivity='internal')
    parts = chunks(source)
    assert len(parts) > 1
    assert parts[0]['start'] == 0 and parts[-1]['end'] == len(source['text'])
    assert all(c['text'] == source['text'][c['start']:c['end']] for c in parts)
    assert all(a['end'] >= b['start'] for a, b in zip(parts, parts[1:]))
    assert chunks(dict(source, text=source['text']+'变更'))[0]['id'] != parts[0]['id']


def test_retrieval_budget_no_match_and_isolation():
    source = dict(id='D1', title='合同', text='办公室装修。'*180+'验收后支付70%尾款。', sensitivity='internal')
    session = {'sources': [source]}
    hits = retrieve(session, '尾款什么时候支付')
    assert hits and '70%' in hits[0]['text']
    assert sum(len(h['text']) for h in hits) <= 2200
    assert not retrieve(session, '火星轨道')
    assert not retrieve({'sources': []}, '尾款')
    session['sources'] = []
    assert not retrieve(session, '尾款') and not session['chunks']


def test_rag_model_receives_chunks_and_citations_survive_reload(client, monkeypatch):
    sid = setup(client)
    monkeypatch.setenv('DECISIONFLOW_API_KEY', 'test-key')
    client.put(f'/api/sessions/{sid}/settings', json={'mode':'proactive','cloud':True})
    async def answer(system, payload):
        doc = payload['sources'][0]
        assert doc['source_id'] and doc['start'] == 0
        return {'answer':'验收后支付70%尾款。','evidence_ids':[doc['id']]}
    monkeypatch.setattr(engine, 'completion', answer)
    s = send(client, sid, '尾款如何支付？', 'question')
    citation = s['messages'][-1]['evidence_ids'][0]
    assert citation in {c['id'] for c in s['chunks']}
    saved = client.get(f'/api/sessions/{sid}').json()
    assert saved['chunks'] == s['chunks']
    deleted = client.delete(f'/api/sessions/{sid}/sources/{s["sources"][0]["id"]}').json()
    assert not deleted['chunks'] and all(m['role']!='assistant' for m in deleted['messages'])


def test_rag_rejects_model_unknown_citation(client, monkeypatch):
    sid = setup(client)
    monkeypatch.setenv('DECISIONFLOW_API_KEY', 'test-key')
    client.put(f'/api/sessions/{sid}/settings', json={'mode':'proactive','cloud':True})
    monkeypatch.setattr(engine, 'completion', AsyncMock(return_value={'answer':'编造','evidence_ids':['foreign:chunk']}))
    s = send(client, sid, '尾款怎么支付？', 'question')
    assert '离线' in s['messages'][-1]['text']
    assert '编造' not in s['messages'][-1]['text']
