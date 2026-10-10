#!/usr/bin/env python3
"""Validate live-shape fixtures against the exact external Fabric contract pin."""
import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from research_agent.service.app import create_app
from research_agent.service.protocol import job_view, tools_list, OUTPUTS
PIN='623bf61358c339cb10297807b3f024b5d9f1f327'

async def main():
 p=argparse.ArgumentParser();p.add_argument('contract',type=Path);a=p.parse_args()
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=a.contract,text=True).strip()==PIN
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=a.contract,text=True).strip()
 schemas={}
 for path in (a.contract/'schemas').rglob('*.json'):
  doc=json.loads(path.read_text())
  if '$id' in doc:schemas[doc['$id']]=doc
 registry=Registry().with_resources([(uri,Resource.from_contents(doc)) for uri,doc in schemas.items()])
 def check(name,value):
  uri='https://fabric.passioncode.ai/agent-contract/0.1.0/schemas/'+name+'.schema.json'
  Draft202012Validator(schemas[uri],registry=registry,format_checker=FormatChecker()).validate(value)
 manifest=json.loads(Path('fabric-agent.json').read_text());check('manifest',manifest)
 tools={t['name']:t for t in tools_list()}
 for cap in manifest['capabilities']:
  name=cap['name'];inp=json.loads(Path('fabric/schemas',name+'.input.json').read_text());out=json.loads(Path('fabric/schemas',name+'.output.json').read_text())
  assert tools[name]['inputSchema']==inp
  assert out==OUTPUTS[name]
 with tempfile.TemporaryDirectory() as root:
  app=create_app(Path(root),'host','agent');rt=app.state.runtime
  job=rt.create({'kind':'tutorial'},'contract','00-'+'1'*32+'-'+'2'*16+'-01')
  check('interop-job',job_view(job))
  rt.decide(job['id'],job['proposal']['digest'],True)
  await rt.tasks[job['id']]
  job=rt.store.job(job['id']);check('interop-job',job_view(job));check('interop-result',job['result'])
  check('service-usage',rt.store.usage());check('service-events-page',rt.store.events())
  import httpx
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:18764') as client:
   check('service-well-known',(await client.get('/.well-known/fabric-service')).json())
 print(json.dumps({'contractCommit':PIN,'checks':['manifest','tool-schemas-match','input-required-job','completed-job','interop-result','events','usage','well-known'],'status':'PASS'}))
asyncio.run(main())
