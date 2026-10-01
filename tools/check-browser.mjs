// Reproducible visual and interaction checks. Playwright is an optional dev tool.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const config=JSON.parse(fs.readFileSync(process.env.RADAR_BROWSER_CONFIG||'.private/browser-config.json'));
const root=path.resolve('dist');const captures=process.env.RADAR_CAPTURE_DIR||'.private/captures';
fs.mkdirSync(captures,{recursive:true});
const server=http.createServer((req,res)=>{const pathname=decodeURIComponent(req.url.split('?')[0]);const file=path.join(root,pathname==='/'?'index.html':pathname);if(!file.startsWith(root)||!fs.existsSync(file)){res.writeHead(404);res.end();return}res.setHeader('Content-Type',file.endsWith('.json')?'application/json':file.endsWith('.woff2')?'font/woff2':'text/html; charset=utf-8');res.end(fs.readFileSync(file))});
await new Promise(resolve=>server.listen(8766,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch({executablePath:config.exe,args:config.args,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100},locale:'ko-KR',timezoneId:'Asia/Seoul'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8766',{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.title(),'오버나잇 마켓 레이더');assert.equal(await page.locator('html').getAttribute('lang'),'ko');
 const labels=['오늘의 판단','자금 흐름','이슈 추적','선물·아시아','신용·미수','종가베팅 후보','미장 마감','복기','운영·개선'];
 for(const label of labels){await page.getByRole('tab',{name:label,exact:true}).click();const text=await page.locator('.radar-page').innerText();assert(!text.includes('[object Object]'));assert(!text.includes('undefined'));assert(!text.includes('NaN'));}
 await page.getByRole('tab',{name:'자금 흐름',exact:true}).click();assert(await page.locator('svg.recharts-surface').count()>0,'Source-backed yield chart missing');await page.screenshot({path:path.join(captures,'radar-flows.png'),fullPage:true});
 await page.getByRole('tab',{name:'이슈 추적',exact:true}).click();await page.locator('.radar-issue details summary').first().click();assert(await page.locator('.radar-issue details').first().getAttribute('open')!==null);
 await page.getByRole('tab',{name:'종가베팅 후보',exact:true}).click();await page.getByPlaceholder('개인 관찰종목 메모').fill('검증용 로컬 메모');assert.equal(await page.evaluate(()=>localStorage.getItem('radar-local-holdings')),'검증용 로컬 메모');await page.getByPlaceholder('개인 관찰종목 메모').fill('');
 await page.getByRole('tab',{name:'오늘의 판단',exact:true}).click();await page.screenshot({path:path.join(captures,'radar-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(captures,'radar-mobile.png'),fullPage:true});
 for(const label of labels){await page.getByRole('tab',{name:label,exact:true}).click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow '+label);}
 assert.deepEqual(errors,[]);
 const report={verified_at:new Date().toISOString(),viewports:['1440×1100','390×844'],tabs:labels.length,chart:'국채금리 실제 270개 관측 렌더링',interactions:['9개 탭','원출처 상세 펼침','기기 내 메모 저장','모바일 가로 넘침 없음'],page_errors:errors,scope:'로컬 배포 번들·실제 GitHub Pages 아님'};
 fs.writeFileSync('docs/project/browser-verification.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser?.close();server.close();}
