#!/usr/bin/env python3
"""Materialise schemas from the actual tool definitions, avoiding a second contract."""
import json
from pathlib import Path
from research_agent.service.protocol import CAPABILITIES, JOBS, SCHEMAS, RESULT_SCHEMA, BASE, OUTPUTS
from research_agent.service.store import digest
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'fabric/schemas';folder.mkdir(parents=True,exist_ok=True)
manifest={'contractVersion':'0.1.0','provider':{'id':'https://prowl.chat/fabric/providers/research-agent','revision':5,
 'createdAt':'2026-10-10T00:00:00Z','createdBy':'urn:fabric:operator:prowl-ai','name':'Prowl Research',
 'identity':{'subject':'https://prowl.chat/fabric/providers/research-agent','method':'local-install'},'supportedContractVersions':['0.1.0'],
 'extensions':{'https://fabric.passioncode.ai/agent-contract/extensions/service/0.1':{'descriptor':'prowl-research.default'}}},'capabilities':[]}
for name in CAPABILITIES:
 out=OUTPUTS[name]
 for kind,schema in [('input',SCHEMAS[name]),('output',out)]:
  (folder/(name+'.'+kind+'.json')).write_text(json.dumps({'$id':BASE+name+'.'+kind+'.json',**schema},indent=2)+'\n')
 cap={'id':'https://prowl.chat/fabric/capabilities/'+name,'name':name,'inputSchema':BASE+name+'.input.json','outputSchema':BASE+name+'.output.json',
 'effect':'charge' if name in {'research.run','research.tools.call'} else 'draft' if name in JOBS else 'none',
 'idempotency':'required' if name in JOBS else 'none','dataClasses':['project-internal'],
 'profile':{'kind':'mcp','protocolRevision':'2026-07-28','connection':{'mode':'streamable-http','url':'http://127.0.0.1:18764/mcp'},
 'requiredFeatures':['tool:'+name,'tool:fabric.job.get','tool:fabric.job.cancel'],
 'probes':[{'id':'discovery-only','inputFixture':'https://prowl.chat/fabric/fixtures/discovery.json','outputSchema':BASE+name+'.output.json','timeoutMs':30000,'sideEffectCeiling':'none','assertions':['Admission must use discovery and local fixtures only; do not execute paid tools as a probe.']}]}}
 if name in JOBS:cap['extensions']={'https://fabric.passioncode.ai/agent-contract/extensions/interop/0.1':{'job':True}}
 manifest['capabilities'].append(cap)
manifest['provider']['contentHash']='sha256:'+digest(manifest)
(ROOT/'fabric-agent.json').write_text(json.dumps(manifest,indent=2)+'\n')

(ROOT/"research_agent/service/manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
