"""Dimensionally explicit calculations; no market coverage or causal inference."""
from collections import defaultdict
from statistics import median
from .calendars import parse_time
from .analysis import safe_rows


def intraday_activity(current,history,cutoff,minimum=10):
    """Compare cumulative turnover at the SAME session minute and universe only."""
    valid=safe_rows(history,cutoff)
    out=[]
    for r in safe_rows(current,cutoff):
        matching=[h for h in valid if all(h.get(k)==r.get(k) for k in ('ticker','venue','currency','session','session_minute','universe')) and h.get('trade_date','')<r.get('trade_date','') and h.get('turnover') is not None]
        days={h['trade_date']:h['turnover'] for h in matching}
        values=list(days.values());baseline=median(values) if values else None
        out.append({'ticker':r['ticker'],'sample_days':len(values),'median_turnover':baseline,'activity':r['turnover']/baseline if len(values)>=minimum and baseline and r.get('turnover') is not None else None,'status':'같은 장중 시각 비교' if len(values)>=minimum else '동일 시각 역사 표본 부족'})
    return out


def breadth(rows):
    groups=defaultdict(list)
    for r in rows:
        if not r.get('observed_at') or not r.get('time_verified') or r.get('dayChangePct') is None:continue
        groups[(r.get('market'),r.get('venue'),r.get('observed_at'),r.get('universe'))].append(r)
    out=[]
    for key,items in groups.items():
        up=sum(r['dayChangePct']>0 for r in items);down=sum(r['dayChangePct']<0 for r in items)
        ranked=sorted(items,key=lambda r:r.get('turnover') or 0,reverse=True);den=sum(r.get('turnover') or 0 for r in items)
        sectors=defaultdict(list)
        for r in items:sectors[r.get('sector','미확인')].append(r['dayChangePct'])
        out.append({'market':key[0],'venue':key[1],'observed_at':key[2],'universe':key[3],'population':len(items),'rising_share':up/len(items),'falling_share':down/len(items),'flat_share':(len(items)-up-down)/len(items),'top5_concentration':sum(r.get('turnover') or 0 for r in ranked[:5])/den if den else None,'positive_sector_share':sum(median(v)>0 for v in sectors.values())/len(sectors),'scope':'관찰 대상 내·시장 전체 아님'})
    return out


def relative_strength(row,benchmark):
    if any(row.get(k)!=benchmark.get(k) for k in ('observed_at','session','return_basis')):return None
    if row.get('dayChangePct') is None or benchmark.get('dayChangePct') is None:return None
    return row['dayChangePct']-benchmark['dayChangePct']


def after_close_change(current,baseline):
    """No rolling futures or ETF substitution; exact instrument and contract."""
    for k in ('instrument','contract','expiry','venue','currency'):
        if current.get(k)!=baseline.get(k):return {'changePct':None,'status':'계약·시장 기준 불일치'}
    if not baseline.get('aligned_to_kr_close'):return {'changePct':None,'status':'국내 종가 기준시각 미검증'}
    if current.get('roll_adjustment') or baseline.get('roll_adjustment'):return {'changePct':None,'status':'롤오버·조정 분리 필요'}
    if not baseline.get('price') or current.get('price') is None:return {'changePct':None,'status':'기준값 미확보'}
    if parse_time(current['observed_at'])<parse_time(baseline['observed_at']):return {'changePct':None,'status':'과거 시세'}
    return {'changePct':(current['price']/baseline['price']-1)*100,'status':'국내 마감 이후 동일 계약 변화'}


def leverage_history(current,history,cutoff,minimum=120):
    result=[]
    for r in safe_rows(current,cutoff):
        matching=[h for h in safe_rows(history,cutoff) if all(h.get(k)==r.get(k) for k in ('name','unit','definition','denominator_definition')) and h.get('reference_date','')<r.get('reference_date','') and h.get('value') is not None]
        matching=sorted({h['reference_date']:h for h in matching}.values(),key=lambda h:h['reference_date'])
        values=[h['value'] for h in matching];previous=matching[-1] if matching else None
        v=r.get('value');den=r.get('market_cap')
        result.append({'name':r['name'],'reference_date':r['reference_date'],'history_count':len(values),'change':v-previous['value'] if v is not None and previous else None,'percentile':sum(x<=v for x in values)/len(values)*100 if v is not None and len(values)>=minimum else None,'market_cap_ratio':v/den if v is not None and den and r.get('market_cap_same_date_currency_unit') else None,'overheat':'잔고 증가만으로 하락을 예측할 수 없음','fragility':'가격 하락·변동성·실제 반대매매 함께 확인·개별 종목 반대매매 확정 아님'})
    return result


def event_reaction(before,after,benchmark_before,benchmark_after):
    if not before.get('price') or not benchmark_before.get('price'):return None
    if before.get('instrument')!=after.get('instrument'):return None
    for a,b in ((before,benchmark_before),(after,benchmark_after)):
        if a.get('observed_at')!=b.get('observed_at'):return None
    excess=((after['price']/before['price']-1)-(benchmark_after['price']/benchmark_before['price']-1))*100
    return {'relative_return_pp':excess,'classification':'확인된 사실','causality':'발표 전후 상대 반응·원인 확정 아님','alternative':'동시 사건·기존 추세·선반영·시장 공통 요인 확인 필요'}
