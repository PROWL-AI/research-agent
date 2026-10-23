import {webkit} from 'playwright';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const root=await mkdtemp(join(tmpdir(),'prowl-ui-'));
const origin='http://127.0.0.1:18765';
const env={...process.env};for(const key of ['PROWL_API_KEY','RESEARCH_LLM_API_KEY','OPENROUTER_API_KEY'])delete env[key];
const child=spawn('.venv/bin/python',['-m','research_agent.service.cli','serve','--root',root,'--port','18765','--log-dir',join(root,'logs')],{env,stdio:['ignore','ignore','pipe']});
let error='';child.stderr.on('data',d=>error+=d.toString());
// Screenshots go to a fresh temporary folder unless DASHBOARD_EVIDENCE_DIR names one on purpose:
// a routine run must never overwrite committed evidence.
const evidence=process.env.DASHBOARD_EVIDENCE_DIR||await mkdtemp(join(tmpdir(),'prowl-ui-shots-'));await mkdir(evidence,{recursive:true});
let browser;
try{
 for(let i=0;i<80;i++){try{if((await fetch(origin+'/.well-known/fabric-service')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const token=(await readFile(join(root,'host.token'),'utf8')).trim();
 const r=await fetch(origin+'/fabric/v1/login-code',{method:'POST',headers:{Authorization:'Bearer '+token}});
 assert.equal(r.status,200);const login=await r.json();
 browser=await webkit.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+login.url);await page.getByRole('heading',{name:'Исследования, на виду.'}).waitFor();
 await page.screenshot({path:evidence+'/overview-desktop.png',fullPage:true});
 // No provider keys in this run: the header chip says so, in Russian, as do the kit's pickers.
 await page.locator('#service-chip',{hasText:'Работает с ограничениями'}).waitFor();
 assert.equal(await page.locator('#fd-theme option:checked').textContent(),'Графит');
 assert.equal(await page.locator('#fd-scheme option[value=auto]').textContent(),'Как в системе');
 await page.getByRole('button',{name:'Открыть учебный пример',exact:true}).click();
 await page.getByRole('heading',{name:'Разрешить этот запрос?'}).waitFor();
 await page.screenshot({path:evidence+'/approval-desktop.png',fullPage:true});
 await page.getByText('Инициатор: Оператор (панель)',{exact:true}).waitFor();  // created in the panel, not a declared name
 await page.getByRole('button',{name:'Разрешить запуск',exact:true}).click();
 await page.locator('.badge.completed').waitFor({timeout:15000});
 await page.getByRole('tab',{name:'Данные',exact:true}).click();
 await page.getByRole('cell',{name:'example.org',exact:true}).waitFor();
 await page.screenshot({path:evidence+'/data-desktop.png',fullPage:true});
 await page.getByRole('tab',{name:'Шаги',exact:true}).click();
 assert.equal(await page.locator('.timeline li').count(),3);
 await page.getByRole('tab',{name:'Отчёт',exact:true}).click();
 await page.getByText('Учебный отчёт',{exact:false}).waitFor();
 await page.locator('[data-nav="costs"]').click();
 await page.getByRole('heading',{name:'Расходов пока нет'}).waitFor();
 await page.locator('[data-nav="chains"]').click();
 await page.getByRole('heading',{name:'Учебная цепочка'}).waitFor();
 await page.locator('[data-nav="settings"]').click();
 await page.locator('[name="cheap_model"]').fill('test/model');
 await page.waitForTimeout(5200);
 assert.equal(await page.locator('[name="cheap_model"]').inputValue(),'test/model');
 await page.getByRole('button',{name:'Проверить изменения'}).click();
 await page.getByRole('button',{name:'Применить',exact:true}).click();
 await page.getByText('Версия 2',{exact:true}).waitFor();
 await page.locator('[data-nav="requests"]').click();
 await page.locator('#search').fill('not-a-request');
 await page.getByRole('heading',{name:'Ничего не найдено'}).waitFor();
 await page.locator('#search').fill('');
 await page.setViewportSize({width:360,height:740});
 await page.waitForTimeout(200);
 // the kit prepared the wide box: it is marked exactly when it overflows (ED-4)
 assert(await page.evaluate(()=>{const b=document.querySelector('#request-table .fd-scroll');return b.hasAttribute('data-fd-overflow')===(b.scrollWidth>b.clientWidth+1)&&b.hasAttribute('data-fd-overflow');}),'scroll box not prepared');
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'requests 360 overflow');
 await page.screenshot({path:evidence+'/requests-360.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('[data-nav="learn"]').click();
 await page.getByRole('heading',{name:'От запроса к данным.'}).waitFor();
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:evidence+'/learn-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
 await page.locator('[data-nav="overview"]').click();
 await page.getByRole('heading',{name:'Исследования, на виду.'}).waitFor();
 await page.screenshot({path:evidence+'/overview-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overview mobile overflow');
 // Offline preserves the last snapshot and reports its age.
 await page.route('**/api/state',r=>r.abort());
 await page.getByRole('button',{name:'Обновить',exact:true}).click();
 await page.getByText('Нет свежих данных',{exact:true}).waitFor();
 assert(await page.getByRole('heading',{name:'Исследования, на виду.'}).isVisible());
 assert.deepEqual(errors,[]);
 await readability(browser);
 console.log(JSON.stringify({browser:'Playwright WebKit',viewports:['1440x1000','390x844','360x740'],evidence,checks:['empty','status-chip','russian-kit-labels','verified-initiator','scroll-box-prepared','requests-360-no-overflow','approval','tutorial','steps','table','report','fixture-spend-exclusion','chains','dirty-settings','settings-diff','search-empty','mobile-no-overflow','offline-keeps-snapshot','spend-windows','per-report','attention-now-only','older-failures-folded','failure-words-first','coverage-research','coverage-tool'],pageErrors:errors,status:'PASS'}));
}catch(e){console.error(e);throw e;}finally{
 if(browser)await browser.close();
 child.kill('SIGTERM');
 await new Promise(resolve=>{child.once('exit',resolve);setTimeout(resolve,11000).unref();});
 if(child.exitCode==null && child.signalCode==null){child.kill('SIGKILL');throw new Error('Shutdown deadline exceeded');}
 await rm(root,{recursive:true,force:true});
 if(error)process.stderr.write(error);
}

// M1-B (B-066, B-076, B-078): a second, seeded service; the first one keeps the empty-state walk.
async function readability(browser){
 const seeded=await mkdtemp(join(tmpdir(),'prowl-ui-fx-'));
 const seed=spawn('.venv/bin/python',['scripts/dashboard-fixtures.py',seeded],{env:{...env,PYTHONPATH:process.cwd()},stdio:['ignore','ignore','inherit']});
 assert.equal(await new Promise(r=>seed.once('exit',r)),0);
 const port='18767',base='http://127.0.0.1:'+port;
 const server=spawn('.venv/bin/python',['-m','research_agent.service.cli','serve','--root',seeded,'--port',port,'--log-dir',join(seeded,'logs')],{env,stdio:['ignore','ignore','pipe']});
 try{
  for(let i=0;i<80;i++){try{if((await fetch(base+'/.well-known/fabric-service')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  const token=(await readFile(join(seeded,'host.token'),'utf8')).trim();
  const login=await (await fetch(base+'/fabric/v1/login-code',{method:'POST',headers:{Authorization:'Bearer '+token}})).json();
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+login.url);await page.getByRole('heading',{name:'Исследования, на виду.'}).waitFor();
  // Spend: three windows and the cost of one report, a lower bound because one call is unpriced.
  const spend=page.locator('[aria-label="Расходы"]');
  await spend.getByText('Расходы · Сегодня (UTC)').waitFor();
  assert.equal(await spend.locator('.metric').nth(0).locator('strong').textContent(),'≥ $0.1500');
  assert.match(await spend.locator('.metric').nth(0).locator('small').textContent(),/3 вызова, 1 без цены/);
  assert.equal(await spend.locator('.metric').nth(3).locator('strong').textContent(),'≥ $0.1500');
  await spend.getByText('расходы за 30 дней на 1 готовый отчёт').waitFor();
  // Attention: the pending decision and the recent failure; the tutorial failure is not there; older ones fold.
  const panel=page.locator('section.panel',{has:page.getByRole('heading',{name:'Требуют внимания'})});
  assert.equal(await panel.locator('.row a').count(),2);
  await panel.getByRole('button',{name:'Ещё 3 ошибки старше 3 дней'}).waitFor();
  await panel.getByText('чаще всего: прервано').waitFor();
  await page.screenshot({path:evidence+'/overview-readability-desktop.png',fullPage:true});
  await panel.getByRole('button',{name:'Ещё 3 ошибки старше 3 дней'}).click();
  await page.getByRole('heading',{name:'Запросы'}).waitFor();
  assert.equal(await page.locator('#filter').inputValue(),'failed');
  // A failure says what happened and the next step first; the raw text is under «Подробности».
  const jobs=(await page.evaluate(async()=>(await (await fetch('/api/state',{credentials:'same-origin'})).json()).jobs));
  const open=async pick=>{await page.goto(base+'/dashboard#/requests/'+jobs.find(pick).id);await page.getByRole('link',{name:'← Все запросы'}).waitFor();await page.waitForTimeout(150);};
  await open(j=>j.request.inputs?.brand==='Recent');
  await page.getByRole('heading',{name:'Истекло время запроса.'}).waitFor();
  assert(!(await page.getByText('Wall-clock timeout reached.').isVisible()),'raw text shown before the toggle');
  await page.getByText('Подробности',{exact:true}).click();
  await page.getByText('прогон: cancelled').waitFor();
  await page.getByText('продолжение через research.run с resumeJobId',{exact:false}).waitFor();
  // Coverage, in Russian, on a research job and on a tool job.
  for(const kind of ['research','tool']){
   await open(j=>j.request.kind===kind&&j.status==='completed');
   await page.getByRole('tab',{name:'Данные',exact:true}).click();
   await page.getByText('Охват источника.',{exact:false}).waitFor();
   await page.getByText('только реклама, показанная в Европе',{exact:false}).waitFor();
  }
  await page.screenshot({path:evidence+'/coverage-desktop.png',fullPage:true});
  await page.setViewportSize({width:360,height:740});await page.goto(base+'/dashboard#/overview');
  await page.getByRole('heading',{name:'Исследования, на виду.'}).waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'readability 360 overflow');
  await page.screenshot({path:evidence+'/overview-readability-360.png',fullPage:true});
  assert.deepEqual(errors,[]);
 }finally{
  server.kill('SIGTERM');await new Promise(r=>{server.once('exit',r);setTimeout(r,11000).unref();});
  await rm(seeded,{recursive:true,force:true});
 }
}
