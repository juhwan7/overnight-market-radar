"""Bounded collection → validation → independent rules → publication snapshot.

Only entitled public outputs enter src/data.json. Raw responses stay private.
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import providers
from .analysis import safe_rows,rate_summary,risk_assessment,choose_candidates,gap_scenarios,turnover_concentration,digest_id,METHOD_VERSION
from .calendars import iso,parse_time,KST,NY,holding_window,market_clock,session_for
from .http import HttpClient,SourceError
from .feed import load_feed,CATEGORIES

ROOT=Path(__file__).resolve().parents[1]
APP_ID='dashboard:38e4a7f3-8af0-49c5-b5ca-faf938b031a7'
LABELS={1:'실제 수신 검증 대상',2:'계정·키·권한 필요',3:'유료 상품·별도 서비스 필요',4:'확보 방법 미확인'}
LINKS={'rates':('미국 재무부',providers.TREASURY_DOC),'events':('BLS·연준',providers.BLS_CALENDAR),'issues':('SEC·연준',providers.SEC_DOC),'markets':('시세 공식 문서','https://github.com/koreainvestment/open-trading-api'),'sources':('출처·권한 검증','https://openapi.krx.co.kr/'),'diary':('시점 보존 규칙','https://docs.github.com/en/actions'),'operations':('GitHub Actions','https://docs.github.com/en/actions')}

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)

def query(rows,name,now,description):
    provider,url=LINKS[name]
    return {'rows':rows,'source':{'label':provider,'provider':provider,'executedAt':iso(now),'description':description,'links':[{'label':'공식 안내','url':url}],
        'evidenceFlow':['공식 수신','필드·시각 검증','규칙 분석','공개 허용 결과'],'metricDefinitions':{'주의':'가격·거래대금은 실제 순유입이 아닙니다. 기준시각·범위를 확인하세요.'}}}

def previous_rows(previous,key):return previous.get('queries',{}).get(key,{}).get('rows',[])

def state_for(entry,status,now,rows=None,error=None):
    r=dict(entry,status=status,checked_at=iso(now),error=error)
    r['row_count']=len(rows or [])
    r['last_data_date']=max((str(x.get('date') or x.get('reference_date') or x.get('observed_at') or x.get('at') or '') for x in rows or []),default=None)
    r['last_success_at']=iso(now) if status=='수신 검증 완료' else None
    return r

def research_rows(path,now):
    doc=read_json(path,{})
    rows=[]
    for r in doc.get('issues',[]):
        if r.get('classification') not in ('확인된 사실','근거가 있는 해석','조건부 시나리오','확인되지 않음'):continue
        if not str(r.get('url','')).startswith('https://') or not r.get('id') or not r.get('available_at'):continue
        if not r.get('title') or not r.get('summary'):continue
        rows.append(dict(r,source_id='research',catalyst_verified=False))
    return safe_rows(rows,now)

def run(now=None,output=None):
    wall=time.monotonic();now=now or datetime.now(timezone.utc)
    config=read_json(ROOT/'config/radar.json');entries=read_json(ROOT/'config/sources.json')
    output=Path(output or ROOT/'src/data.json');previous=read_json(output,{})
    if previous.get('generatedAt') and parse_time(previous['generatedAt'])>now:raise SourceError('오래된 실행 결과의 덮어쓰기 차단')
    client=HttpClient(ROOT/'.private/cache',now)
    public={};states={};failures=[];covered=[]
    jobs={'treasury':lambda:providers.treasury(client,now),'bls':lambda:providers.bls_events(client,now),'fomc':lambda:providers.fomc_events(client,now),'fed_news':lambda:providers.fed_news(client,now),'sec':lambda:providers.sec_filings(client,now,config['watchlist_us'])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks={key:pool.submit(fn) for key,fn in jobs.items()}
        for entry in entries:
            key=entry['id']
            if key not in tasks:
                states[key]=state_for(entry,'미확보',now);continue
            try:
                result=tasks[key].result()
                if key=='sec':result,covered,errors=result;failures.extend(errors)
                public[key]=safe_rows(result,now)
                states[key]=state_for(entry,'수신 검증 완료',now,public[key])
            except Exception as exc:
                # Exceptions can carry private request details: expose sanitized categories only.
                error=str(exc) if isinstance(exc,SourceError) else '파싱·스키마 검증 실패'
                failures.append(entry['name']+': '+error)
                old_key={'treasury':'rates','bls':'events','fomc':'events','fed_news':'issues','sec':'issues'}[key]
                public[key]=[r for r in previous_rows(previous,old_key) if r.get('source_id')==key]
                states[key]=state_for(entry,'수집 실패·마지막 정상 자료',now,public[key],error)
                states[key]['last_success_at']=previous.get('radar',{}).get('source_states',{}).get(key,{}).get('last_success_at')
    feed={category:[] for category in CATEGORIES}
    if os.getenv('MARKET_FEED_URL'):
        try:
            feed,errors=load_feed(client,os.environ['MARKET_FEED_URL'],now);failures.extend(errors)
            for key in feed:
                if key not in states:continue
                if feed[key]:
                    stale=any((now-parse_time(r['observed_at'])).total_seconds()>900 for r in feed[key]) if key in ('market_kr','market_us','futures','fx','asia','assets') else any((now.date()-datetime.fromisoformat(r['reference_date']).date()).days>4 for r in feed[key]) if key=='leverage_kr' else False
                    states[key]=state_for(states[key],'자료 지연' if stale else '수신 검증 완료',now,feed[key])
        except Exception:
            failures.append('허가된 시세 피드: 인증·수신·필드·공개 권한 확인 필요')
            for category in CATEGORIES:
                query_key='leverage' if category=='leverage_kr' else 'flows' if category in ('investor_flows','fund_flows') else 'events' if category=='earnings' else 'markets'
                feed[category]=[r for r in previous_rows(previous,query_key) if r.get('category')==category and r.get('source_id')=='licensed']
                if category in states:
                    states[category]=state_for(states[category],'수집 실패·마지막 정상 자료',now,feed[category],'피드 수신·검증 실패')
    if os.getenv('KIS_APP_KEY') and os.getenv('KIS_APP_SECRET'):
        from .kis import KisClient
        try:
            rows=KisClient(client,now,ROOT/'.private/cache').domestic(config['kis'])
            write_json(ROOT/'.private/kis-latest.json',rows)
            if config['publication_approvals']['kis']:
                feed['market_kr']=rows
                states['market_kr']=state_for(states['market_kr'],'시세 기준시각 미검증',now,rows)
            else:failures.append('KIS 수신·비공개 보관 완료. 공개 재표시 권한 확인 전 브라우저 전송 차단.')
        except Exception:failures.append('KIS 인증·시세 권한·응답 스키마 확인 필요')
    rates=public.get('treasury',[])
    events=sorted(public.get('bls',[])+public.get('fomc',[])+feed['earnings'],key=lambda r:r['at'])
    old_rates={(x.get('date'),x.get('maturity')):x for x in previous_rows(previous,'rates')}
    for row in rates:
        old=old_rates.get((row.get('date'),row.get('maturity')))
        if old and old.get('yieldPct')==row.get('yieldPct'):row['available_at']=old['available_at']
    old_events={x.get('id'):x for x in previous_rows(previous,'events')}
    for row in events:
        old=old_events.get(row.get('id'))
        if old and old.get('at')==row.get('at'):row['available_at']=old['available_at']
    issues=public.get('fed_news',[])+public.get('sec',[])+research_rows(ROOT/'research/latest.json',now)
    old_issues={r['id']:r for r in previous_rows(previous,'issues') if r.get('id')}
    for r in issues:
        old=old_issues.get(r['id'])
        if old:
            r['first_seen_at']=old.get('first_seen_at',old.get('available_at'));r['available_at']=old.get('available_at',r['available_at'])
            r['state']='영향 지속' if r.get('summary')==old.get('summary') else '새로 바뀐 내용 확인'
        r.setdefault('market_response','시장 반응 미검증');r.setdefault('next_check','공식 본문·관련 시세·동시 사건 확인');r.setdefault('new_content','원출처 접수·발표 확인')
    issues=list({r['id']:r for r in issues}.values());issues.sort(key=lambda r:r['at'],reverse=True)
    window=holding_window(now,config['calendar']);risk=risk_assessment(events,window,states,rates,now)
    markets=feed['market_kr']+feed['market_us']+feed['futures']+feed['fx']+feed['asia']+feed['assets']
    candidates,excluded=choose_candidates(feed['market_kr'],issues,now,config,risk)
    concentration=turnover_concentration(feed['market_kr']+feed['market_us'])
    dates={'KRX':market_clock(now,'KRX',config['calendar']),'NYSE':market_clock(now,'NYSE',config['calendar'])}
    # Every preclose observation has its own immutable file. Never use final close to rewrite it.
    diary_dir=ROOT/'data/diary';diary_dir.mkdir(parents=True,exist_ok=True)
    kr=now.astimezone(KST)
    if dates['KRX']['phase']=='정규장 진행' and (15,10)<=(kr.hour,kr.minute)<=(15,29):
        name=kr.strftime('%Y-%m-%d_%H%M')+'.json'
        file=diary_dir/name
        if not file.exists():write_json(file,{'kind':'마감 전 판단','date':kr.date().isoformat(),'available_at':iso(now),'window':window,'candidates':candidates,'excluded':excluded,'risk':risk,'scenarios':gap_scenarios(risk,now),'method_version':METHOD_VERSION,'scope':'당시 공개·수신 검증 범위','result':'다음 거래일 시가 데이터 대기'})
    diary=[read_json(p,{}) for p in sorted(diary_dir.glob('*.json'))[-90:]]
    # Briefing requires a real verified exchange close; missing prices stay explicit.
    us=dates['NYSE'];briefings=read_json(ROOT/'data/briefings.json',[])
    if us.get('close') and now>=parse_time(us['close'])+timedelta(minutes=20) and not any(r['date']==us['date'] for r in briefings):
        confirmed=[r for r in feed['market_us'] if r.get('session')=='정규장' and r.get('final') is True and parse_time(r['observed_at'])>=parse_time(us['close'])]
        briefings.append({'date':us['date'],'available_at':iso(now),'exchange_close':us['close'],'status':'확정 시세 수신' if confirmed else '공식 마감 확인·시세 미확보','scope':'허가된 피드 관찰 대상' if confirmed else '시세 범위 없음·전체 미국 시장 순위 제공 불가','summary':'관찰 범위의 확정 정규장 자료 확인' if confirmed else '정규장 종료는 달력으로 확인했으나 가격·거래 집중·시간외 반전은 판단 보류.','issues':[r for r in issues if r.get('source_id')=='sec'][:8],'next_check':'국내 개장 전 실제 선물·환율·관련 기업 시간외·국내 공시 확인','stocks':confirmed})
        write_json(ROOT/'data/briefings.json',briefings[-90:])
    operations=read_json(ROOT/'data/operations.json',[])
    slot=now.replace(minute=(now.minute//10)*10,second=0,microsecond=0)
    missed=0
    if operations:
        missed=max(0,int((slot-parse_time(operations[-1]['slot'])).total_seconds()//600)-1)
    operation={'id':os.getenv('GITHUB_RUN_ID','local-'+now.strftime('%Y%m%dT%H%M%S')),'slot':iso(slot),'started_at':iso(now),'checked_at':iso(datetime.now(timezone.utc)),'missed_slots':missed,'missed_policy':'현재 값을 과거 슬롯으로 복사하지 않음','calls':client.calls,'seconds':round(time.monotonic()-wall,2),'failures':failures,'deployment':'배포 전·공개 URL 검증 필요'}
    operations.append(operation);operations=operations[-config['keep_runs']:];write_json(ROOT/'data/operations.json',operations)
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,stderr=subprocess.DEVNULL,text=True).strip()
    except Exception:commit='로컬·저장소 미생성'
    help_rows=[{'id':e['id'],'name':e['name'],'reason':e['fields'],'status':states[e['id']]['status'],'task':'공식 계정·시세 권한·공개 표시 범위 확인 후 Secrets와 허가 피드 연결','secret':'KIS_APP_KEY·KIS_APP_SECRET' if e['id']=='market_kr' else 'MARKET_FEED_URL','url':e['documentation'],'cost':e['cost'],'alternative':e['alternative']} for e in entries if states[e['id']]['status']!='수신 검증 완료']
    from .metrics import breadth,leverage_history
    snapshot={'surface':'dashboard','id':APP_ID,'title':'오버나잇 마켓 레이더','generatedAt':iso(now),'status':'partial','buildStatus':'complete','filters':[],
      'radar':{'window':window,'risk':risk,'scenarios':gap_scenarios(risk,now),'candidates':candidates,'excluded':excluded,'source_states':states,'market_clocks':dates,'rate_summary':rate_summary(rates),'concentration':concentration,'briefings':briefings[-30:],'help':help_rows,'source_commit':commit,'method_version':METHOD_VERSION,'us_covered':covered,'limitations':['국내·미국 장중 시세·선물·원달러·아시아·국내 신용·공식 펀드 흐름 미연결','BLS·FOMC 외 국채입찰·기업 실적 예정·돌발 이슈의 포괄적 일정 미확보','국내 달력은 2026년 10월만 확인. 다음 범위 미확인 시 판단 보류','정확한 10분 수집·중단 시 독립 감시는 보장하지 않음'],'budget':{'runs_per_day':144,'runs_per_month_30d':4320,'estimated_runner_minutes_3min':12960,'baseline_llm_api_cost':0,'public_standard_runner_cost':'공개 저장소 표준 러너 무료 범위 확인 필요·유료 데이터 별도','max_runtime_minutes':8,'retention_days':90}},
      'queries':{'rates':query(rates,'rates',now,'공식 일별 par yield. 일중 환율·선물 대용이나 자금 유입액이 아닙니다.'),'events':query(events,'events',now,'BLS 공식 일정과 FOMC 날짜·통상 발표시간. 결과·방향 미확정.'),'issues':query(issues,'issues',now,'공식 공시·발표 메타데이터. 시장 반응과 인과관계는 미검증.'),'markets':query(markets,'markets',now,'허가된 실제 시세만 표시. 빈 값은 0이나 ETF 대용으로 대체하지 않음.'),'flows':query(feed['investor_flows']+feed['fund_flows'],'markets',now,'투자자군 순매수와 설정·환매 흐름을 분리. 거래 집중과 실제 흐름은 다름.'),'leverage':query(feed['leverage_kr'],'sources',now,'국내 공식 신용·미수·실제 반대매매·예탁금. 기준일과 공식 정의 필수.'),'sources':query(list(states.values()),'sources',now,'제공기관·빈도·인증·비용·보관·공개 권한·실제 수신 상태'),'diary':query(diary,'diary',now,'당시 이용 가능 정보만 보존. 후보 0개와 미확보도 보존.'),'operations':query(operations,'operations',now,'예정 슬롯·실제 시작·요청 수·누락·부분 실패·배포 검증')}}
    snapshot['radar']['breadth']=breadth(feed['market_kr']+feed['market_us'])
    snapshot['radar']['leverage_analysis']=leverage_history(feed['leverage_kr'],previous_rows(previous,'leverage'),now)
    snapshot['radar']['snapshot_id']=digest_id(snapshot)
    write_json(output,snapshot)
    write_json(ROOT/'public/radar-manifest.json',{'build_id':operation['id'],'source_commit':commit,'snapshot_id':snapshot['radar']['snapshot_id'],'generated_at':iso(now),'method_version':METHOD_VERSION,'public_url_verified':False})
    print(json.dumps({'snapshot':snapshot['radar']['snapshot_id'],'at':iso(now),'rates':len(rates),'events':len(events),'issues':len(issues),'candidates':len(candidates),'risk':risk['decision'],'calls':client.calls,'failures':failures},ensure_ascii=False))
    return snapshot

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--at');parser.add_argument('--output');args=parser.parse_args()
    run(parse_time(args.at) if args.at else None,args.output)
