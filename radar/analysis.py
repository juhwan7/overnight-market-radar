"""Transparent conservative rules; observed turnover is not money inflow."""
import hashlib
from collections import defaultdict
from datetime import timedelta
from .calendars import parse_time,iso

METHOD_VERSION='rules-1.0'


def safe_rows(rows,cutoff):
    out=[]
    for row in rows:
        availability=row.get('available_at')
        if not availability:
            continue
        try:
            if parse_time(availability)<=cutoff:
                out.append(row)
        except (ValueError,TypeError):pass
    return out


def turnover_concentration(rows):
    """Group only a common population/time/venue/currency; sums reconcile."""
    groups=defaultdict(list)
    for row in rows:
        if row.get('observed_at') and row.get('time_verified') and row.get('turnover') is not None and row['turnover']>=0:
            key=(row.get('market'),row.get('venue'),row.get('currency'),row.get('observed_at'),row.get('universe'))
            groups[key].append(row)
    out=[]
    for key,items in groups.items():
        denominator=sum(r['turnover'] for r in items)
        if denominator<=0:continue
        sectors=defaultdict(float)
        for r in items:sectors[r.get('sector') or '업종 미확인']+=r['turnover']
        for sector,total in sectors.items():
            out.append({'market':key[0],'venue':key[1],'currency':key[2],'observed_at':key[3],
               'sector':sector,'turnover':total,'turnoverShare':total/denominator,'denominator':denominator,
               'universe':key[4],'population':len(items),'classification':'거래 집중','scope':'관찰 대상 내 비중'})
    return sorted(out,key=lambda r:(r['market'] or '',-r['turnoverShare']))


def rate_summary(rows):
    result=[]
    for maturity in ('2년','10년','30년'):
        series=sorted((r for r in rows if r['maturity']==maturity),key=lambda r:r['date'])
        if not series:continue
        last=series[-1];prev=series[-2] if len(series)>1 else None
        delta=(last['yieldPct']-prev['yieldPct'])*100 if prev else None
        result.append(dict(last,changeBp=round(delta,2) if delta is not None else None,previousDate=prev['date'] if prev else None,
          interpretation='금리 상승 관측. 성장주 할인율 부담 가능성·실제 시세 반응은 별도 확인.' if delta and delta>0 else '금리 하락 관측. 경기 우려와 완화 기대를 구분해야 함.' if delta and delta<0 else '최근 두 발표 관측 사이 금리 변화 없음.' if delta==0 else '비교 관측 부족.'))
    return result


def choose_candidates(rows,issues,now,config,risk):
    rows=safe_rows(rows,now);issues=safe_rows(issues,now)
    selected=[];excluded=[]
    for r in rows:
        reasons=[]
        if r.get('market')!='KR':continue
        if r.get('instrument_type') not in ('보통주','보통주 조회조건'):reasons.append('보통주 확인 필요')
        if any(s in r.get('name','') for s in ('스팩','SPAC')):reasons.append('스팩 제외')
        if not r.get('time_verified') or not r.get('observed_at'):reasons.append('실제 시세 기준시각 미검증')
        elif (now-parse_time(r['observed_at'])).total_seconds()>config['candidate_max_age_seconds']:reasons.append('핵심 가격 지연')
        if r.get('turnover') is None or r['turnover']<config['candidate_min_turnover_krw']:reasons.append('유동성 기준 미충족·자료 없음')
        if r.get('dayChangePct') is None or r['dayChangePct']>config['candidate_max_day_gain_pct']:reasons.append('과열 기준 초과·등락률 없음')
        if r.get('closePosition') is None or r['closePosition']<config['candidate_min_close_position']:reasons.append('장중 가격 위치 기준 미충족')
        catalyst=[i for i in issues if i.get('ticker')==r['ticker'] and i.get('catalyst_verified') and i.get('classification')=='확인된 사실']
        if not catalyst:reasons.append('후보 촉매·공식 근거 미검증')
        if not r.get('corporate_actions_checked'):reasons.append('기업행사·거래제한 미검증')
        if risk['decision']=='판단 보류':reasons.append('시장 핵심 데이터·달력 확인 필요')
        if reasons:
            excluded.append({'ticker':r['ticker'],'name':r.get('name',r['ticker']),'reasons':' · '.join(reasons),'available_at':iso(now)})
        else:
            selected.append(dict(r,reason='거래 집중·유동성·가격 위치·공식 촉매 조건 충족',catalysts=catalyst,classification='근거가 있는 해석'))
    selected=sorted(selected,key=lambda r:r['turnover'],reverse=True)
    for r in selected[config['candidate_limit']:]:
        excluded.append({'ticker':r['ticker'],'name':r['name'],'reasons':'후보 수 제한에 따라 추가 관찰','available_at':iso(now)})
    return selected[:config['candidate_limit']],excluded


def risk_assessment(events,window,source_states,rate_rows,now):
    critical=('market_kr','futures','fx','leverage_kr','bls','fomc')
    missing=[k for k in critical if source_states.get(k,{}).get('status')!='수신 검증 완료']
    if not window.get('end'):missing.append('holding_calendar')
    if window.get('end'):
        end=parse_time(window['end'])
        exposed=[r for r in events if now<=parse_time(r['at'])<=end]
    else:exposed=[]
    high=[r for r in exposed if r.get('severity')=='높음']
    summaries=rate_summary(rate_rows)
    rate_jump=next((r for r in summaries if r['maturity']=='10년' and (r.get('changeBp') or 0)>=10),None)
    observed='높음' if high else '주의' if exposed or rate_jump else '관찰상 큰 예정 사건 미발견'
    decision='판단 보류' if missing else '높음' if high else '주의'
    checks=[{'name':'보유구간 주요 경제 발표','status':'주의' if exposed else '확인','detail':f'확인된 일정 중 {len(exposed)}건 노출. BLS·FOMC 외 실적·국채입찰·돌발 사건은 미포함.'},
      {'name':'국내 종가 이후 선물·환율','status':'미확보' if any(k in missing for k in ('futures','fx')) else '확인','detail':'실제 선물 월물과 원달러 시세시각·국내 마감 이후 변화를 확인해야 함.'},
      {'name':'신용·미수 취약성','status':'미확보' if 'leverage_kr' in missing else '확인','detail':'최근 발표 기준일과 반대매매 정의·증감 확인 필요.'},
      {'name':'매수 후보·기업 개별 위험','status':'확인 필요','detail':'보유종목별 공시·기업행사·실적 일정은 별도 검증 필요.'}]
    return {'decision':decision,'observed_risk':observed,'data_confidence':'낮음' if missing else '핵심 입력 확인',
      'missing':missing,'exposed_events':exposed,'checks':checks,'reason':'핵심 선물·환율·국내 시세·신용 자료를 확보하지 못해 낮은 위험으로 판단하지 않습니다.' if missing else '규칙 기반 점검. 돌발 사건과 손절 미체결 위험은 남습니다.',
      'method_version':METHOD_VERSION,'probability':None,'score':None}


def gap_scenarios(risk,now):
    missing=bool(risk['missing'])
    return [
      {'name':'갭상승 시나리오','classification':'조건부 시나리오','conditions':'국내 마감 후 실제 지수선물·관련 업종 강세, 환율·금리 안정, 후보의 검증된 호재 유지',
       'invalidation':'해외 강세 소멸, 관련 기업 가이던스 악화, 후보의 장후반 가격·재료 약화',
       'current':'성립 여부 판단 보류' if missing else '추가 관찰 필요','probability':None,'available_at':iso(now)},
      {'name':'갭하락 시나리오','classification':'조건부 시나리오','conditions':'국내 마감 후 선물 약세·환율 급등·금리 충격·관련 기업 악재 또는 후보 개별 위험',
       'invalidation':'악재 반응이 진정되고 실제 시장·업종 강도가 회복',
       'current':'핵심 입력 미확보로 하방 위험 배제 불가' if missing else '추가 관찰 필요','probability':None,'available_at':iso(now)},
      {'name':'방향 불명·관망','classification':'조건부 시나리오','conditions':'예정 이벤트 결과 대기, 신호 충돌, 시세 지연·공백, 유사 조건 표본 부족',
       'invalidation':'필수 데이터가 확보되고 사건 결과·시장 반응이 일관되게 확인',
       'current':'현재 우선 적용' if missing else '조건 발생 시 적용','probability':None,'available_at':iso(now)}]


def empirical_gaps(bars,cutoff,minimum=60):
    gaps=[]
    groups=defaultdict(list)
    for r in safe_rows(bars,cutoff):
        if r.get('timeframe')=='일별':
            groups[(r.get('ticker'),r.get('venue'))].append(r)
    for items in groups.values():
        ordered=sorted(items,key=lambda r:r['observed_at'])
        for previous,current in zip(ordered,ordered[1:]):
            if current.get('corporate_action') or previous.get('corporate_action'):continue
            if not current.get('consecutive_verified'):continue
            if not previous.get('close') or current.get('open') is None:continue
            gaps.append(current['open']/previous['close']-1)
    if len(gaps)<minimum:return {'sample':len(gaps),'status':'표본 부족','quantiles':None,'probability':None}
    gaps.sort()
    return {'sample':len(gaps),'status':'과거 갭 분포·미래 확률 아님','quantiles':{str(p):gaps[round((len(gaps)-1)*p)] for p in (0.05,0.5,0.95)},'probability':None}


def digest_id(payload):
    import json
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()[:16]
