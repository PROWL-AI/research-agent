import asyncio
import json
from pathlib import Path
import pytest
import httpx
from research_agent.service.app import create_app
from research_agent.service.store import Store, Conflict
from research_agent.service.runtime import Runtime
from research_agent.service.protocol import Protocol, META, job_view, tools_list

@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path,'host-value','agent-value')

@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:18764') as c:
        yield c
    await app.state.runtime.close()

async def login(client):
    r=await client.post('/fabric/v1/login-code',headers={'Authorization':'Bearer host-value'})
    url=r.json()['url']
    r=await client.get(url)
    assert r.status_code==302
    return url

@pytest.mark.parametrize('path,method',[('/api/state','GET'),('/api/jobs','POST'),('/fabric/v1/events','GET'),('/fabric/v1/usage','GET'),('/mcp','POST')])
async def test_private_surfaces_deny_anonymous(client,path,method):
    assert (await client.request(method,path)).status_code==401

async def test_tokens_are_role_separated(client):
    assert (await client.post('/mcp',headers={'Authorization':'Bearer host-value'},json={})).status_code==401
    assert (await client.post('/fabric/v1/login-code',headers={'Authorization':'Bearer agent-value'})).status_code==401

async def test_login_single_use_and_csrf(client):
    url=await login(client)
    assert (await client.get(url)).status_code==401
    assert (await client.get('/api/state')).status_code==200
    assert (await client.post('/api/jobs',json={})).status_code==403
    assert (await client.get('/api/state',headers={'Origin':'https://evil.test'})).status_code==403
    assert (await client.get('/api/state',headers={'Host':'evil.test:18764'})).status_code==403

async def test_tutorial_lifecycle_receipts_and_no_real_cost(client,app,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Network must not be used by tutorial')
    monkeypatch.setattr(httpx.AsyncClient,'post',httpx.AsyncClient.post)
    # Runtime provider path is forbidden, independent of HTTP transport itself.
    monkeypatch.setattr(Runtime,'live',forbidden)
    await login(client)
    headers={'X-Prowl-Request':'1'}
    data={'request':{'kind':'tutorial'},'idempotencyKey':'sample-1'}
    first=(await client.post('/api/jobs',json=data,headers=headers)).json()
    second=(await client.post('/api/jobs',json=data,headers=headers)).json()
    assert first['id']==second['id'] and first['status']=='input_required'
    conflict=await client.post('/api/jobs',json={**data,'request':{'kind':'tutorial','context':{'chain':'different'}}},headers=headers)
    assert conflict.status_code==409
    r=await client.post('/api/jobs/'+first['id'],json={'action':'approve','digest':first['proposal']['digest']},headers=headers)
    assert r.status_code==200
    repeat=await client.post('/api/jobs/'+first['id'],json={'action':'approve','digest':first['proposal']['digest']},headers=headers)
    assert repeat.status_code==409
    await app.state.runtime.tasks[first['id']]
    detail=(await client.get('/api/jobs/'+first['id'])).json()
    assert detail['job']['status']=='completed' and len(detail['calls'])==3
    assert detail['job']['result']['output']['rows'][0]['visits']==12800
    assert app.state.store.usage()['days']==[]

async def test_cancel_is_terminal_and_receipts_survive(app):
    rt=app.state.runtime
    j=rt.create({'kind':'tutorial'},'cancel')
    rt.decide(j['id'],j['proposal']['digest'],True)
    await asyncio.sleep(.05)
    rt.cancel(j['id'])
    await asyncio.sleep(.05)
    assert rt.store.job(j['id'])['status']=='cancelled'
    assert len(rt.store.calls(j['id']))==1
    rt.store.transition(j['id'],'completed','completed')
    assert rt.store.job(j['id'])['status']=='cancelled'

async def test_stale_decision_and_config_snapshot(app):
    rt=app.state.runtime;j=rt.create({'kind':'tutorial'},'stale')
    with pytest.raises(Conflict):rt.decide(j['id'],'bad',True)
    config=rt.store.config();values={k:v for k,v in config.items() if k!='revision'}
    values['cheap_model']='test/model'
    assert rt.store.configure(1,values)['revision']==2
    assert rt.store.job(j['id'])['config']['cheap_model']!='test/model'
    with pytest.raises(Conflict):rt.store.configure(1,values)

async def test_recovery_never_reexecutes(tmp_path):
    s=Store(tmp_path);j=s.create({'kind':'tutorial'},'restart')[0]
    s.decide(j['id'],j['proposal']['digest'],True)
    call=s.start_call(j['id'],'tool','pending',{})
    s.db.close();s=Store(tmp_path);s.recover()
    assert s.job(j['id'])['phase']=='interrupted'
    assert s.calls(j['id'])[0]['status']=='unknown'
    assert s.job(j['id'])['error']['code']=='interrupted'

async def test_mcp_trace_job_and_unknown_id(app):
    p=Protocol(app.state.runtime)
    parent='00-'+'1'*32+'-'+'2'*16+'-01'
    body={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'research.tutorial','arguments':{'idempotencyKey':'mcp'},'_meta':{'traceparent':parent}}}
    result,status=await p.handle(body,{})
    assert status==200
    job_id=result['result']['structuredContent']['job']['id']
    trace=result['result']['_meta']['traceparent']
    assert trace!=parent and trace.split('-')[1]=='1'*32
    job=app.state.store.job(job_id)
    app.state.runtime.decide(job_id,job['proposal']['digest'],True)
    await app.state.runtime.tasks[job_id]
    body['params'].update(name='fabric.job.get',arguments={'id':job_id})
    got,_=await p.handle(body,{})
    assert got['result']['_meta']['traceparent']==got['result']['structuredContent']['job']['result']['trace']['traceparent']==trace
    body['params']['arguments']={'id':'does-not-exist'}
    got,_=await p.handle(body,{})
    assert got['result']['isError'] and got['result']['structuredContent']['error']['code']=='unknown-job'

async def test_modern_metadata_validation_and_discovery(app):
    p=Protocol(app.state.runtime)
    body={'jsonrpc':'2.0','id':1,'method':'server/discover','params':{'_meta':{META+'protocolVersion':'2026-07-28',META+'clientInfo':{'name':'test','version':'1'},META+'clientCapabilities':{}}}}
    got,status=await p.handle(body,{})
    assert status==400 and got['error']['code']==-32020
    got,status=await p.handle(body,{'mcp-protocol-version':'2026-07-28','mcp-method':'server/discover'})
    assert status==200 and got['result']['supportedVersions'][0]=='2026-07-28'
    assert got['result']['resultType']=='complete'

async def test_agent_cannot_approve_its_own_job(app):
    rt=app.state.runtime;j=rt.create({'kind':'tutorial'},'permission')
    p=Protocol(rt)
    body={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'fabric.job.get','arguments':{'id':j['id'],'inputResponses':{'decision':{'action':'accept'}}}}}
    got,_=await p.handle(body,{})
    assert got['result']['isError']
    assert rt.store.job(j['id'])['status']=='input_required'

async def test_usage_partial_costs_and_failures(tmp_path):
    s=Store(tmp_path);j=s.create({'kind':'tool'},'cost')[0]
    a=s.start_call(j['id'],'tool','data',{});s.finish_call(a,status='failed',costUsd=.6,costBasis='provider')
    b=s.start_call(j['id'],'llm','model',{});s.finish_call(b,status='unknown')
    report=s.usage();day=report['days'][0]
    assert day['costUsd']==.6 and day['unpricedCalls']==1 and day['calls']==2
    assert next(m for m in day['byModel'] if m['model']=='model')['costUsd'] is None

async def test_static_csp_and_xss_data(client):
    await login(client)
    r=await client.get('/dashboard')
    assert r.status_code==200 and "script-src 'self'" in r.headers['content-security-policy']
    assert 'unsafe-inline' not in r.headers['content-security-policy']
    assert (await client.get('/static/not-allowed.txt')).status_code==404

async def test_call_and_settings_validation(app):
    rt=app.state.runtime
    with pytest.raises(ValueError):rt.create({'kind':'tutorial','context':{'requester':123}},'bad')
    with pytest.raises(ValueError):rt.create({'kind':'tutorial','params':{'api_key':'secret'}},'bad')
    for value in [0,5,'2']:
        values={k:v for k,v in rt.store.config().items() if k!='revision'};values['parallel_jobs']=value
        with pytest.raises(ValueError):rt.store.configure(1,values)

async def test_billed_tool_failure_is_persisted(tmp_path):
    from mcp.types import CallToolResult,TextContent
    from research_agent.service.runtime import ObservedProwl
    from research_agent.prowl_client import ToolCallError
    store=Store(tmp_path);job=store.create({'kind':'tool'},'failure')[0]
    class Session:
        async def call_tool(self,*args,**kwargs):
            return CallToolResult(content=[TextContent(type='text',text=json.dumps({'success':False,'error_class':'upstream_error','billing':{'actual_cost_usd':.6}}))])
    prowl=ObservedProwl('fake','https://example.invalid').observe(store,job);prowl._session=Session()
    with pytest.raises(ToolCallError):await prowl.call_tool('example',{})
    assert store.calls(job['id'])[0]['costUsd']==.6
    assert store.calls(job['id'])[0]['status']=='failed'

async def test_llm_truncated_billed_response_recorded_once(tmp_path):
    from research_agent.service.runtime import ObservedLLM
    from research_agent.llm import LLMError
    store=Store(tmp_path);job=store.create({'kind':'research'},'llm')[0]
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'partial'}}],'usage':{'prompt_tokens':10,'completion_tokens':5,'cost':.2}})
    llm=ObservedLLM('https://example.invalid','fake','cheap','strong').observe(store,job)
    await llm._client.aclose();llm._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):await llm.complete([{'role':'user','content':'x'}])
    await llm.aclose()
    receipt=store.calls(job['id'])[0]
    assert len(calls)==1 and receipt['costUsd']==.2 and receipt['inputTokens']==10 and receipt['status']=='failed'

async def test_expired_approval_cannot_start(app):
    rt=app.state.runtime;j=rt.create({'kind':'tutorial'},'expired')
    j['proposal']['expiresAt']='2000-01-01T00:00:00Z'
    with rt.store.db:rt.store._save(j)
    with pytest.raises(Conflict):rt.decide(j['id'],j['proposal']['digest'],True)
    assert rt.tasks=={}

async def test_missing_provider_credentials_is_actionable(client,monkeypatch):
    monkeypatch.delenv('PROWL_API_KEY',raising=False)
    await login(client)
    r=await client.post('/api/jobs',headers={'X-Prowl-Request':'1'},json={'request':{'kind':'tool','tool':'example','params':{}},'idempotencyKey':'live'})
    assert r.status_code==400 and 'credentials' in r.json()['error']

async def test_artifacts_cannot_escape(app,tmp_path):
    from research_agent.service.protocol import artifact
    j=app.state.runtime.create({'kind':'tutorial'},'paths')
    with pytest.raises(ValueError):artifact(app.state.store,j['id'],'../../host.token')
    folder=tmp_path/'runs'/j['id'];folder.mkdir(parents=True)
    (tmp_path/'sensitive').write_text('not public')
    (folder/'report.md').symlink_to(tmp_path/'sensitive')
    with pytest.raises(KeyError):artifact(app.state.store,j['id'],'report.md')

async def test_second_process_cannot_acquire_lock_or_create_tokens(tmp_path):
    import subprocess,sys
    from research_agent.service.cli import lock
    fd=lock(tmp_path)
    try:
        r=subprocess.run([sys.executable,'-m','research_agent.service.cli','serve','--root',str(tmp_path),'--port','18766'],capture_output=True,timeout=5)
        assert r.returncode==75 and not (tmp_path/'host.token').exists()
    finally:__import__('os').close(fd)
