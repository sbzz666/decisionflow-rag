"""Local chunk-level BM25 retrieval. No network, embeddings or cross-session corpus."""
import hashlib
import math
import re
from collections import Counter


def tokens(text):
    result = re.findall(r'[a-z0-9]+', text.lower())
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        result.extend(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            result.append(run)
    return result


def chunks(source, size=500, overlap=80):
    text = source['text']
    revision = hashlib.sha256(text.encode()).hexdigest()[:12]
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind(c, start + size // 2, end) for c in '\n。！？；')
            if boundary >= 0:
                end = boundary + 1
        out.append(dict(id=f'{source["id"]}:{revision}:{start}', source_id=source['id'],
                        title=source['title'], text=text[start:end], start=start, end=end,
                        revision=revision, sensitivity=source['sensitivity']))
        if end == len(text):
            break
        start = end - overlap
    return out


def index_sources(session):
    # Rebuild from live documents: no stale cache after deletion or replacement.
    session['chunks'] = [c for source in session['sources'] for c in chunks(source)]
    return session['chunks']


def retrieve(session, query, limit=5, budget=2200):
    corpus = index_sources(session)
    if re.search(r'货款|付清|全款|尾款|预付|账期', query):
        query += ' 付款 验收 账期'
    terms = set(tokens(query))
    bags = [Counter(tokens(c['title'] + ' ' + c['text'])) for c in corpus]
    if not bags or not terms:
        return []
    avg = sum(sum(b.values()) for b in bags) / len(bags) or 1
    df = Counter(t for b in bags for t in b)
    ranked = []
    for chunk, bag in zip(corpus, bags):
        length, score = sum(bag.values()), 0.0
        for term in terms & bag.keys():
            freq = bag[term]
            idf = math.log(1 + (len(bags) - df[term] + .5) / (df[term] + .5))
            score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length / avg))
        if score > 0:
            ranked.append(dict(chunk, score=round(score, 6)))
    selected, used = [], 0
    for item in sorted(ranked, key=lambda c: (-c['score'], c['id'])):
        if used + len(item['text']) > budget:
            continue
        selected.append(item)
        used += len(item['text'])
        if len(selected) >= limit:
            break
    return selected
