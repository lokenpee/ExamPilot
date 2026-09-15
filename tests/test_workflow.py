"""Integration: real FastAPI + SQLite + stdio MCP; deterministic model double.

The double exists only in tests. It is never available as a product model or UI mode.
"""
import io
import json
import time

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.store import Store
from backend.providers import Settings
from backend.mcp_client import KnowledgeClient
from backend.engine import Engine


class ModelDouble:
    def __init__(self):
        self.config={"concurrency":2,"model":"test-double"}
        self.job_id="test"
        self.native_calls=0

    async def json(self,system,value,role):
        if role=='knowledge-extraction':
            return {"knowledge_points":[{"name":"事务","summary":"原子性与回滚","source_ids":[s['source_id'] for s in value['segments']]}]}
        if role=='planning':
            return {"summary":"测试专用规划","slots":[{**s,"knowledge_point":"事务","focus":"原子性"} for s in value['base_slots']],"warnings":[],"unresolved":[]}
        if role=='question-review':
            return {"warnings":[]}
        if role=='generation-requirements':
            return {**value['previous'],"type":"short_answer","knowledge_point":"事务","difficulty":"hard","focus":"新要求"}
        if role=='generation':
            if value.get('conversation'):
                assert value['previous_candidate']['stem'], 'Follow-up generation must receive the previous full candidate'
            r=value['request'];t=r['type'];u=r['score_units']
            q={"type":t,"difficulty":r['difficulty'],"score_units":u,"knowledge_point":"事务","stem":f"测试 {r.get('id', 'candidate')}（{t}）：事务的原子性有什么含义？","options":[],"rubric":[],"answer":"操作全部完成或全部回滚。","analysis":"根据输入资料原文。","source_ids":[value['evidence'][0]['source_id']]}
            if t in ('single_choice','multiple_choice'):
                q['options']=[{"id":"A","text":"全部完成"},{"id":"B","text":"失败回滚"},{"id":"C","text":"只修改一部分"},{"id":"D","text":"不需要提交"}]
                q['answer']=['A'] if t=='single_choice' else ['A','B']
            elif t=='true_false':q['answer']=True
            elif t=='fill_blank':q.update(stem=f"测试 {r.get('id', 'candidate')}：原子性要求操作全部完成或全部____。",answer=['回滚'])
            else:q['rubric']=[{"text":"解释完整执行或回滚","score_units":u}]
            return q
        raise AssertionError(role)

    async def complete(self,messages,role,tools=None,tool_choice=None,max_tokens=None):
        self.native_calls+=1
        name=tool_choice['function']['name']
        if name=='search':
            args={"queries":json.loads(messages[1]['content'])['queries']}
        else:
            result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
            args={"ids":list(dict.fromkeys(m['chunk_id'] for r in result['results'] for m in r['matches']))}
        return {"role":"assistant","content":None,"tool_calls":[{"id":f"call_{self.native_calls}","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}


@pytest.fixture
def client(tmp_path,monkeypatch):
    import backend.api as module
    store=Store(tmp_path)
    settings=Settings(store)
    mcp=KnowledgeClient(store)
    engine=Engine(store,settings,mcp)
    monkeypatch.setattr(settings,'provider',lambda job_id='system':ModelDouble())
    for name,value in [('store',store),('settings',settings),('mcp',mcp),('engine',engine)]:
        monkeypatch.setattr(module,name,value)
    with TestClient(module.app) as c:
        yield c,store


def wait_job(c,job_id):
    for _ in range(150):
        result=c.get('/api/jobs/'+job_id).json()
        if result['status'] not in ('queued','running'):
            assert result['status']=='succeeded',result
            return result
        time.sleep(.04)
    raise AssertionError('Job timeout')


def prepare(c):
    project=c.post('/api/projects',json={'title':'Integration test'}).json()['id']
    doc=Document();doc.add_paragraph('事务的原子性要求操作全部完成，失败时全部回滚。事务的隔离性用于控制并发影响。')
    data=io.BytesIO();doc.save(data)
    upload=c.post(f'/api/projects/{project}/documents',files={'file':('notes.docx',data.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert upload.status_code==202,upload.text
    wait_job(c,upload.json()['job_id'])
    config={'title':'Integration exam','total_score_units':60,'duration_minutes':60,'ratios':[30,50,20],'sections':[{'type':t,'count':1,'score_units':10} for t in ['single_choice','multiple_choice','true_false','fill_blank','short_answer','calculation']]}
    plan=c.post(f'/api/projects/{project}/plans',json={'config':config}).json()
    wait_job(c,plan['id'])
    state=c.get(f'/api/projects/{project}').json()
    planned=state['plan']
    generated=c.post(f"/api/plans/{planned['id']}/confirm",json={'version':planned['version']},headers={'Idempotency-Key':'generate-once'})
    assert generated.status_code==202,generated.text
    wait_job(c,generated.json()['id'])
    return project,generated.json()['id']


def test_real_mcp_and_full_six_type_workflow(client):
    c,store=client
    assert c.get('/api/health').json()['mcp']['tools']==['search','get_chunk_context']
    project,job_id=prepare(c)
    state=c.get(f'/api/projects/{project}').json();exam=state['exam']
    assert len(exam['questions'])==6
    assert exam['checks']['can_export']
    traces=c.get('/api/jobs/'+job_id+'/traces').json()
    tool_calls=[t for t in traces if t['name']=='tool_called']
    assert [t['tool'] for t in tool_calls]==['search','get_chunk_context']
    assert all(t['transport']=='stdio' for t in tool_calls)
    again=c.post(f"/api/plans/{state['plan']['id']}/confirm",json={'version':1},headers={'Idempotency-Key':'generate-once'})
    assert again.json()['id']==job_id
    exported=c.post(f"/api/exams/{exam['id']}/exports",json={'expected_revision':exam['revision']})
    assert exported.status_code==200,exported.text
    artifacts=exported.json()['artifacts'];assert len(artifacts)==2
    assert len({a['exam_revision'] for a in artifacts})==1
    assert c.get('/api/artifacts/'+artifacts[0]['id']).content.startswith(b'PK')

    # No vacancy, no AI conversation. Delete first, then refine a candidate.
    assert c.post(f"/api/exams/{exam['id']}/vacancies/missing/messages",json={}).status_code==404
    q=exam['questions'][0]
    v=c.delete(f"/api/exams/{exam['id']}/questions/{q['id']}",headers={'If-Match':str(q['version'])}).json()
    state=c.get(f'/api/projects/{project}').json()
    assert len(state['exam']['questions'])==5
    assert state['exam']['target_score_units']==60
    assert not state['exam']['checks']['can_export']
    for text in ('请改为难的简答题','请解释更清楚一些'):
        v=c.get(f'/api/projects/{project}').json()['vacancies'][0]
        job=c.post(f"/api/exams/{exam['id']}/vacancies/{v['id']}/messages",json={'message':text,'expected_version':v['version']}).json()
        wait_job(c,job['id'])
    state=c.get(f'/api/projects/{project}').json();v=state['vacancies'][0]
    assert len(state['exam']['questions'])==5  # Unadopted candidates do not count.
    assert len(v['candidate_history'])==2
    assert v['candidate']['type']=='short_answer' and v['candidate']['difficulty']=='hard'
    traces=c.get('/api/jobs/'+job['id']+'/traces').json()
    assert any(t['name']=='evidence_cache_hit' for t in traces)
    assert not any(t['name']=='tool_called' for t in traces)
    payload={'candidate_id':v['candidate']['id'],'expected_version':v['version']}
    route=f"/api/exams/{exam['id']}/vacancies/{v['id']}/adopt"
    assert c.post(route,json=payload).status_code==200
    assert c.post(route,json=payload).status_code==200  # Idempotent adoption.
    state=c.get(f'/api/projects/{project}').json()
    assert len(state['exam']['questions'])==6 and not state['vacancies']
    assert state['exam']['checks']['can_export']
    assert c.post(f"/api/exams/{exam['id']}/vacancies/{v['id']}/restore",json={'expected_version':v['version']}).status_code==409


def test_generation_lock_manual_review_and_target_total(client):
    c,store=client;project,_=prepare(c)
    state=c.get(f'/api/projects/{project}').json();exam=state['exam'];q=exam['questions'][0]
    lock={'id':'lock','project_id':project,'kind':'generate','status':'running','payload':{'exam_id':exam['id']}}
    store.put('jobs',lock)
    assert c.delete(f"/api/exams/{exam['id']}/questions/{q['id']}",headers={'If-Match':'1'}).status_code==409
    lock['status']='cancelled';store.put('jobs',lock)
    edited=c.patch(f"/api/exams/{exam['id']}/questions/{q['id']}",json={'expected_version':q['version'],'question':{'stem':'请重新判断：事务为何需要原子性？'}})
    assert edited.status_code==200,edited.text
    q=edited.json()
    state=c.get(f'/api/projects/{project}').json();assert state['exam']['checks']['pending_review']==[q['id']]
    assert c.post(f"/api/exams/{exam['id']}/questions/{q['id']}/review",json={'expected_version':q['version']}).status_code==200
    assert c.patch(f"/api/exams/{exam['id']}/questions/{q['id']}",json={'expected_version':1,'question':{}}).status_code==409
    c.delete(f"/api/exams/{exam['id']}/questions/{q['id']}",headers={'If-Match':str(q['version'])})
    state=c.get(f'/api/projects/{project}').json();current=state['exam']
    c.patch(f"/api/exams/{exam['id']}",json={'expected_revision':current['revision'],'target_score_units':50})
    state=c.get(f'/api/projects/{project}').json()
    assert state['exam']['checks']['can_export'] and state['vacancies']


def test_scope_and_tampered_source_rejected(client):
    c,store=client;project,_=prepare(c)
    from backend.retrieval import chunk_context
    other=store.put('corpora',{'id':'other_v1','chunk_ids':[]})
    state=c.get(f'/api/projects/{project}').json();exam=state['exam']
    citation=exam['questions'][0]['citations'][0]
    result=chunk_context(store,'other',1,[citation['chunk_id']])
    assert result['results'][0]['status']=='error'
    stored=store.get('exams',exam['id']);stored['questions'][0]['citations'][0]['text']='FORGED SOURCE'
    store.put('exams',stored)
    assert not c.get(f'/api/projects/{project}').json()['exam']['checks']['can_export']
