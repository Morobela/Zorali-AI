"""Graph memory: triple extraction, storage on memory save, and graph query."""
from fastapi.testclient import TestClient

from app.main import app
from app.memory.knowledge_graph import extract_triples

client = TestClient(app)


def test_extract_first_person_facts():
    triples = extract_triples("My name is Charles. I work at Acme. I like Python.")
    assert ("user", "name", "charles") in triples
    assert ("user", "works_at", "acme") in triples
    assert ("user", "likes", "python") in triples


def test_extract_third_person_facts_and_relation_normalisation():
    triples = extract_triples("Charles works at Acme; Acme uses Python. Sarah loves espresso.")
    assert ("charles", "works_at", "acme") in triples
    assert ("acme", "uses", "python") in triples
    # "loves" normalises to the canonical "likes" relation
    assert ("sarah", "likes", "espresso") in triples


def test_extract_ignores_unparseable_text():
    assert extract_triples("!!! ??? random noise without structure") == []
    assert extract_triples("") == []


def test_memory_save_stores_triples_and_graph_query_follows_hops():
    p = client.post('/api/project', json={'name': 'graph-mem'}).json()

    saved = client.post('/api/memory', json={
        'project_id': p['id'],
        'text': 'Charles works at Acme. Acme uses Python.',
    }).json()
    assert saved['triples'], 'triples should be extracted at save time'

    # Direct entity match: "charles" appears in the query.
    res = client.get(f"/api/memory/graph?project_id={p['id']}&q=Where does Charles work?").json()
    facts = {(t['subject'], t['relation'], t['object']) for t in res['triples']}
    assert ('charles', 'works_at', 'acme') in facts
    # One-hop expansion: acme was matched via charles, so acme→python surfaces too.
    assert ('acme', 'uses', 'python') in facts
    assert 'charles —works_at→ acme' in res['context']


def test_graph_query_anchors_first_person_to_user_node():
    p = client.post('/api/project', json={'name': 'graph-me'}).json()
    client.post('/api/memory', json={'project_id': p['id'], 'text': 'I work at Initech.'})
    res = client.get(f"/api/memory/graph?project_id={p['id']}&q=where do I work").json()
    facts = {(t['subject'], t['relation'], t['object']) for t in res['triples']}
    assert ('user', 'works_at', 'initech') in facts


def test_deleting_memory_cascades_triples():
    p = client.post('/api/project', json={'name': 'graph-del'}).json()
    saved = client.post('/api/memory', json={'project_id': p['id'], 'text': 'Bob lives in Paris.'}).json()
    assert saved['triples']
    client.delete(f"/api/memory/{saved['id']}")
    res = client.get(f"/api/memory/graph?project_id={p['id']}").json()
    assert res['triples'] == []


def test_semantic_search_reports_mode():
    p = client.post('/api/project', json={'name': 'graph-sem'}).json()
    client.post('/api/memory', json={'project_id': p['id'], 'text': 'prefers dark roast coffee'})
    res = client.get(f"/api/memory/semantic-search?project_id={p['id']}&q=coffee").json()
    # Embeddings are off in tests → lexical hybrid path, and it still finds the memory.
    assert res['mode'] == 'lexical-hybrid'
    assert any('coffee' in r['text'] for r in res['results'])
