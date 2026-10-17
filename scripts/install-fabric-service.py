#!/usr/bin/env python3
"""Install a clean committed snapshot; no provider keys or agent config edits.

With --vault-project NAME the service is launched through Project Observatory's
vault-only consumer: `use_secret.py run --vault-only --env prod NAME
PROWL_API_KEY,RESEARCH_LLM_API_KEY -- <serve>`. The keys live in the vault,
reach the process environment only, and never touch the plist, argv, a file or
a log. Without it the service starts degraded (no provider keys) and says so.
--dry-run prints the launch argv and the slots it needs, installs nothing.
"""
import argparse
import fcntl
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = 'prowl-research'
LABEL = 'chat.prowl.research'
#: The provider keys the service needs, by vault slot name (never a value).
SLOTS = ('PROWL_API_KEY', 'RESEARCH_LLM_API_KEY')


def command(*args, **kw):
    return subprocess.check_output(args, text=True, **kw).strip()


def atomic(path, body):
    temp = path.with_suffix(path.suffix+'.tmp')
    fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'wb') as f: f.write(body)
    os.replace(temp,path)


def missing_slots(project):
    """Slots the vault folder lacks (names only — a value is never read here)."""
    engine=Path(command('project-observatory','full-path'))
    listing=command(sys.executable,str(engine/'tools/vault.py'),'list',project,'prod')
    return [s for s in SLOTS if f'{project}/prod/{s}' not in listing]


def vault_consumer(project):
    """The Observatory vault-only consumer's argv prefix."""
    engine=Path(command('project-observatory','full-path'))
    return [sys.executable,str(engine/'tools/use_secret.py'),'run','--vault-only','--env','prod',project,','.join(SLOTS),'--']


def launch_argv(python,data,port,build,logs,vault_project):
    serve=[python,'-m','research_agent.service.cli','serve','--root',str(data),'--port',str(port),'--build',str(build),'--log-dir',str(logs)]
    return (vault_consumer(vault_project)+serve) if vault_project else serve


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18764)
    p.add_argument('--vault-project',help="Observatory vault folder holding the service's keys (prod slots %s)" % ', '.join(SLOTS))
    p.add_argument('--dry-run',action='store_true',help='print the launch argv and the slots it needs; install nothing')
    a=p.parse_args()
    if sys.platform!='darwin': p.error('This installer supports macOS launchd; manual foreground serve is portable.')
    if a.dry_run:
        base=Path.home()/'.local/share'/ID
        argv=launch_argv(str(base/'releases/<commit>/venv/bin/python'),Path.home()/'Library/Application Support'/ID,a.port,
                         base/'releases/<commit>/build.json',Path.home()/'Library/Logs'/ID,a.vault_project)
        print(json.dumps({'argv':argv,'slots':list(SLOTS) if a.vault_project else [],
                          'missing':missing_slots(a.vault_project) if a.vault_project else [],
                          'keys':'vault-only consumer' if a.vault_project else 'none: the service starts degraded'},indent=2))
        return
    if a.vault_project and missing_slots(a.vault_project):
        p.error(f"vault {a.vault_project}/prod lacks {', '.join(missing_slots(a.vault_project))}: "
                "issue them through Observatory's doors first")
    if command('git','status','--porcelain',cwd=ROOT): p.error('Commit task changes before immutable installation.')
    sha=command('git','rev-parse','HEAD',cwd=ROOT)
    base=Path.home()/'.local/share'/ID
    release=base/'releases'/sha[:12]
    registry=Path.home()/'Library/Application Support/ai.passioncode.fabric/services'
    registry.mkdir(parents=True,exist_ok=True)
    with open(registry/'.prowl-install.lock','a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX)
        for path in registry.glob('*.json'):
            d=json.loads(path.read_text())
            if d.get('origin')==f'http://127.0.0.1:{a.port}' and (d.get('id'),d.get('instance'))!=(ID,'default'):
                p.error('Port already claimed by '+path.name)
        target=registry/(ID+'.default.json')
        if target.exists() and json.loads(target.read_text()).get('installedBy')!='prowl-research-service':
            p.error('Existing descriptor belongs to another installer')
        if not release.exists():
            release.mkdir(parents=True)
            try:
                with tempfile.TemporaryFile() as archive:
                    subprocess.run(['git','archive',sha],cwd=ROOT,stdout=archive,check=True)
                    archive.seek(0)
                    with tarfile.open(fileobj=archive) as tar:tar.extractall(release/'source',filter='data')
                uv=shutil.which('uv')
                if not uv:raise RuntimeError('uv is required; install it explicitly before running this installer')
                subprocess.run([uv,'venv','--python','3.11',str(release/'venv')],check=True)
                subprocess.run([uv,'pip','install','--python',str(release/'venv/bin/python'),str(release/'source')],check=True)
                (release/'build.json').write_text(json.dumps({'commit':sha,'dirty':False}))
            except BaseException:
                shutil.rmtree(release)
                raise
        data=Path.home()/'Library/Application Support'/ID
        logs=Path.home()/'Library/Logs'/ID
        logs.mkdir(parents=True,exist_ok=True,mode=0o700)
        plist=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
        python=str(release/'venv/bin/python')
        argv=launch_argv(python,data,a.port,release/'build.json',logs,a.vault_project)
        payload={'Label':LABEL,'ProgramArguments':argv,'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ExitTimeOut':15,'ProcessType':'Standard',
                 'EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/local/bin','FABRIC_SERVICE_SUPERVISOR':'launchd'},
                 'StandardOutPath':str(logs/'service.log'),'StandardErrorPath':str(logs/'service.log')}
        domain=f'gui/{os.getuid()}'
        overrides=command('launchctl','print-disabled',domain)
        disabled=f'"{LABEL}" => disabled' in overrides
        # Stop only this owned label and wait; never disturb unrelated research agents.
        subprocess.run(['launchctl','bootout',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(50):
            if subprocess.run(['launchctl','print',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:break
            time.sleep(.1)
        else:raise RuntimeError('Previous service did not stop; installation left unchanged')
        plist.parent.mkdir(parents=True,exist_ok=True)
        atomic(plist,plistlib.dumps(payload))
        subprocess.run(['plutil','-lint',str(plist)],check=True)
        descriptor={'protocol':'fabric-service/0.1','id':ID,'instance':'default','name':'Prowl Research','summary':'Research requests, evidence, costs and human decisions',
                    'origin':f'http://127.0.0.1:{a.port}','auth':{'tokenFile':str(data/'host.token')},'lifecycle':{'manager':'launchd','label':LABEL,'plist':str(plist)},
                    'paths':{'data':str(data),'config':str(data),'logs':[str(logs/'events.log'),str(logs/'service.log')]},
                    'commands':{'doctor':[python,'-m','research_agent.service.cli','doctor','--port',str(a.port),'--json']},
                    'source':{'repository':'https://github.com/PROWL-AI/research-agent'},'fabricManifest':str(release/'source/fabric-agent.json'),
                    'installedAt':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'installedBy':'prowl-research-service'}
        atomic(target,(json.dumps(descriptor,indent=2)+'\n').encode())
        if not disabled:
            subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
            for _ in range(480):
                try:
                    with urllib.request.urlopen(descriptor['origin']+'/.well-known/fabric-service',timeout=1) as r: health=json.load(r)
                    if health['service']['build'].get('commit')==sha:break
                except Exception:pass
                time.sleep(.25)
            else:raise RuntimeError('Service did not become ready on expected commit')
        print(json.dumps({'descriptor':str(target),'commit':sha,'disabled':disabled,'release':str(release)}))
        # Retain current + previous release. Only directories made by this installer.
        others=sorted([x for x in (base/'releases').iterdir() if x!=release and (x/'build.json').is_file()],key=lambda x:x.stat().st_mtime,reverse=True)
        for old in others[1:]:shutil.rmtree(old)

if __name__=='__main__':main()
