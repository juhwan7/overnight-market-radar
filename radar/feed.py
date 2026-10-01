"""Explicitly entitled data import. No invented observations or private holdings."""
import json
from .calendars import parse_time
from .http import SourceError

CATEGORIES=('market_kr','market_us','futures','fx','asia','assets','leverage_kr','fund_flows','investor_flows','daily_bars','earnings')
PUBLIC_FIELDS=set(('id source_url observed_at published_at available_at unit currency frequency market venue session ticker name sector price high low turnover volume dayChangePct closePosition instrument_type universe corporate_actions_checked contract expiry exchange delay_status underlying measurement reference_date definition denominator_definition value category timeframe open close corporate_action consecutive_verified at title severity scope channel fact classification time_status final source_id market_cap market_cap_same_date_currency_unit session_minute trade_date return_basis instrument roll_adjustment aligned_to_kr_close afterKrCloseChangePct').split())

def validate_feed(doc,now):
    if doc.get('schema_version')!=1 or doc.get('public_display_permission') is not True:
        raise SourceError('피드 버전·공개 표시 권한 미확인')
    if not doc.get('provider') or not str(doc.get('documentation_url','')).startswith('https://'):
        raise SourceError('제공기관·공식 문서 누락')
    out={};errors=[]
    for category in CATEGORIES:
        out[category]=[]
        for r in doc.get(category,[]):
            try:
                required=('id','source_url','observed_at','published_at','available_at','unit','currency','frequency','market','venue','session')
                if any(r.get(k) in (None,'') for k in required):raise ValueError()
                if not str(r['source_url']).startswith('https://'):raise ValueError()
                if parse_time(r['available_at'])>now or parse_time(r['observed_at'])>now:raise ValueError()
                if parse_time(r['available_at'])<parse_time(r['published_at']):raise ValueError()
                if category=='futures' and any(not r.get(k) for k in ('contract','expiry','exchange','delay_status')):raise ValueError()
                if category=='fund_flows' and r.get('measurement') not in ('공식 순유입·순유출','공식 설정·환매'):raise ValueError()
                if category=='leverage_kr' and any(not r.get(k) for k in ('reference_date','definition','denominator_definition')):raise ValueError()
                if category=='earnings' and any(not r.get(k) for k in ('at','title','channel','severity')):raise ValueError()
                if category in ('market_kr','market_us') and any(r.get(k) is None for k in ('ticker','price','turnover','universe','instrument_type')):raise ValueError()
                out[category].append(dict({k:v for k,v in r.items() if k in PUBLIC_FIELDS},category=category,source_id='licensed',time_verified=True))
            except (ValueError,TypeError,KeyError):errors.append(category+': 레코드 필수값·시각 검증 실패')
    return out,sorted(set(errors))

def load_feed(client,url,now):
    if not url.startswith('https://'):raise SourceError('HTTPS 인증 피드 주소 필요')
    return validate_feed(json.loads(client.get(url,ttl=0)),now)
