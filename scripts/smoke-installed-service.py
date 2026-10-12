import asyncio,json
from pathlib import Path
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
 root=Path.home()/'Library/Application Support/prowl-research';origin='http://127.0.0.1:18764'
 role=(Path.home()/'.config/agentgateway/secrets/roles/prowl').read_text().strip()
 async with streamablehttp_client('http://127.0.0.1:47845/mcp/prowl-research',headers={'x-agw-key':role}) as (r,w,_):
  async with ClientSession(r,w) as mcp:
   await mcp.initialize()
   result=await mcp.call_tool('research.tutorial',{'idempotencyKey':'installed-service-tutorial','context':{'requester':'Codex · проверка подключения','chain':'Учебная цепочка Fabric','node':'research','project':'Prowl — интеграция'}},meta={'traceparent':'00-'+'a1'*16+'-'+'b2'*8+'-01'})
   assert not result.isError
   job_id=result.structuredContent['job']['id']
   pending=await mcp.call_tool('fabric.job.get',{'id':job_id})
   assert pending.structuredContent['job']['status']=='input_required'
   async with httpx.AsyncClient(base_url=origin,follow_redirects=False) as c:
    response=await c.post('/fabric/v1/login-code',headers={'Authorization':'Bearer '+(root/'host.token').read_text().strip()});response.raise_for_status()
    login=await c.get(response.json()['url']);assert login.status_code==302
    job=(await c.get('/api/jobs/'+job_id)).json()['job']
    response=await c.post('/api/jobs/'+job_id,headers={'X-Prowl-Request':'1'},json={'action':'approve','digest':job['proposal']['digest']});response.raise_for_status()
   for _ in range(40):
    result=await mcp.call_tool('fabric.job.get',{'id':job_id})
    job=result.structuredContent['job']
    if job['status']=='completed':break
    await asyncio.sleep(.2)
   assert job['status']=='completed'
   assert job['result']['trace']['traceparent'].split('-')[1]=='a1'*16
   assert len(job['result']['output']['rows'])==3
   async with httpx.AsyncClient() as c:
    usage=(await c.get(origin+'/fabric/v1/usage',headers={'Authorization':'Bearer '+(root/'host.token').read_text().strip()})).json()
   assert usage['days']==[]
   print(json.dumps({'status':'PASS','jobId':job_id,'transport':'gateway → service MCP','decision':'synthetic tutorial approved via operator session','tracePreserved':True,'rows':3,'realUsageDays':0,'providerCalls':0}))
asyncio.run(main())
