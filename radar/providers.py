"""Public official sources; publication policy is enforced by the collector."""
import calendar
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from .calendars import iso, NY, parse_time
from .http import SourceError

TREASURY_DOC = 'https://home.treasury.gov/treasury-daily-interest-rate-xml-feed'
FED_CALENDAR = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
BLS_CALENDAR = 'https://www.bls.gov/schedule/news_release/bls.ics'
SEC_DOC = 'https://www.sec.gov/search-filings/edgar-application-programming-interfaces'


def number(value):
    if value is None or value == '':
        return None
    try:
        result = float(str(value).replace(',', ''))
        return result if result == result and abs(result) < 1e30 else None
    except (ValueError, TypeError):
        return None


def treasury(client, now):
    result = []
    for year in (now.year-1, now.year):
        url = f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}'
        root = ET.fromstring(client.get(url, ttl=3600))
        ns = {'a':'http://www.w3.org/2005/Atom', 'm':'http://schemas.microsoft.com/ado/2007/08/dataservices/metadata', 'd':'http://schemas.microsoft.com/ado/2007/08/dataservices'}
        updated = root.findtext('a:updated', namespaces=ns)
        for entry in root.findall('a:entry', ns):
            props = entry.find('a:content/m:properties', ns)
            if props is None:
                continue
            day = props.findtext('d:NEW_DATE', namespaces=ns)
            if not day or day[:10] > now.astimezone(NY).date().isoformat():
                continue
            for name, label in [('BC_2YEAR','2년'),('BC_10YEAR','10년'),('BC_30YEAR','30년')]:
                value = number(props.findtext('d:'+name, namespaces=ns))
                if value is not None:
                    result.append({'date':day[:10], 'maturity':label, 'yieldPct':value, 'unit':'%', 'source_id':'treasury', 'observed_at':day[:10], 'published_at':None, 'provider_updated_at':updated, 'fetched_at':client.received_at(url), 'available_at':iso(now)})
    if not result:
        raise SourceError('금리 레코드 없음')
    unique = {(r['date'],r['maturity']):r for r in result}
    return sorted(unique.values(),key=lambda r:(r['date'],r['maturity']))[-270:]


def parse_ics(text, now):
    # RFC 5545 unfolded lines, TZID, UTC and floating Eastern times.
    text = re.sub(r'\r?\n[ \t]', '', text)
    out = []
    definitions = {
      'Employment Situation':('미국 고용보고서','높음','고용·임금 → 금리 기대 → 미국 성장주·환율'),
      'Consumer Price Index':('미국 소비자물가지수(CPI)','높음','물가 → 금리 기대 → 성장주·원달러'),
      'Producer Price Index':('미국 생산자물가지수(PPI)','주의','생산자 물가 → 물가 전망·금리'),
      'Job Openings and Labor Turnover Survey':('미국 구인·이직보고서(JOLTS)','주의','고용 수요 → 금리 기대'),
      'Employment Cost Index':('미국 고용비용지수','주의','임금 압력 → 물가·금리'),
      'Productivity and Costs':('미국 생산성·비용','주의','생산성·노동비용 → 기업 마진·물가'),
    }
    for block in text.split('BEGIN:VEVENT')[1:]:
        block = block.split('END:VEVENT')[0]
        props = {}
        for line in block.strip().splitlines():
            if ':' in line:
                key, value = line.split(':',1)
                props[key] = value
        summary = props.get('SUMMARY','')
        match = next((v for k,v in definitions.items() if summary.startswith(k)),None)
        start = next(((k,v) for k,v in props.items() if k.startswith('DTSTART')),None)
        if not match or not start or len(start[1]) < 15:
            continue
        key,value = start
        raw = datetime.strptime(value.rstrip('Z'),'%Y%m%dT%H%M%S')
        tzname = key.split('TZID=')[-1] if 'TZID=' in key else 'America/New_York'
        tzname = {'US-Eastern':'America/New_York','US/Eastern':'America/New_York'}.get(tzname,tzname)
        dt = raw.replace(tzinfo=timezone.utc if value.endswith('Z') else ZoneInfo(tzname))
        if not now-timedelta(days=2) <= dt <= now+timedelta(days=60):
            continue
        label,severity,path = match
        out.append({'id':'bls-'+props.get('UID', hashlib.sha256(value.encode()).hexdigest()[:12]), 'title':label, 'at':iso(dt), 'severity':severity, 'scope':'글로벌시장', 'channel':path, 'fact':'공식 발표 일정 확인. 발표 결과와 시장 방향은 미확정.', 'classification':'확인된 사실', 'source_id':'bls', 'url':'https://www.bls.gov/schedule/'+str(dt.year)+'/home.htm', 'time_status':'공식 시간', 'fetched_at':iso(now), 'available_at':iso(now)})
    return sorted(out,key=lambda r:r['at'])


def bls_events(client,now):
    rows = parse_ics(client.get(BLS_CALENDAR,ttl=3600),now)
    for row in rows:row['fetched_at']=client.received_at(BLS_CALENDAR)
    if not rows:
        raise SourceError('향후 발표 일정을 찾지 못함')
    return rows


def fomc_events(client,now):
    doc = client.get(FED_CALENDAR,ttl=21600)
    out=[]
    for year in (now.year,now.year+1):
        section = re.search(r'<h[234][^>]*>\s*(?:<a[^>]*>)?\s*'+str(year)+r' FOMC Meetings.*?(?=<h[234][^>]*>\s*(?:<a[^>]*>)?\s*20\d\d FOMC Meetings|$)',doc,re.S|re.I)
        if not section:
            continue
        blocks = re.findall(r'<div class="fomc-meeting[^"]*"[^>]*>(.*?)</div>\s*</div>',section[0],re.S)
        # Extract pairs directly; markup can wrap the month and dates separately.
        pairs = re.findall(r'fomc-meeting__month[^>]*>\s*(?:<[^>]+>)*\s*([A-Za-z]+).*?fomc-meeting__date[^>]*>\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?)',section[0],re.S)
        for month,span in pairs:
            try:
                m = list(calendar.month_name).index(month)
                day = int(re.split(r'[-–]',span)[-1].strip())
                dt = datetime(year,m,day,14,0,tzinfo=NY)
            except (ValueError,TypeError):
                continue
            if now-timedelta(days=2) <= dt <= now+timedelta(days=60):
                out.append({'id':f'fomc-{year}-{m:02}-{day:02}', 'title':'미국 FOMC 정책 결정', 'at':iso(dt), 'severity':'높음', 'scope':'글로벌시장', 'channel':'정책금리·전망 → 글로벌 할인율·환율', 'fact':'회의 날짜는 연준 공식 달력. 14시 미국 동부 시각은 통상 발표시간을 적용한 추정으로, 별도 공지 시 수정.', 'classification':'조건부 시나리오', 'source_id':'fomc', 'url':FED_CALENDAR, 'time_status':'통상 시간 적용·별도 확인 필요', 'fetched_at':iso(now),'available_at':iso(now)})
    if not out:
        raise SourceError('FOMC 달력 파싱 또는 향후 일정 확인 실패')
    for row in out:row['fetched_at']=client.received_at(FED_CALENDAR) if hasattr(client,'received_at') else iso(now)
    return out


def fed_news(client,now):
    feed_url='https://www.federalreserve.gov/feeds/press_all.xml'
    root=ET.fromstring(client.get(feed_url,ttl=1200))
    from email.utils import parsedate_to_datetime
    out=[]
    for item in root.findall('.//item'):
        title=item.findtext('title') or ''
        url=item.findtext('link') or ''
        raw=item.findtext('pubDate')
        try:
            published=parsedate_to_datetime(raw).astimezone(timezone.utc)
        except (TypeError,ValueError):
            continue
        if published > now or published < now-timedelta(days=14):
            continue
        if 'FOMC statement' in title:
            label='연준 FOMC 성명 발표'; severity='높음'; channel='정책금리·정책 전망'
        elif 'projections' in title.lower():
            label='연준 경제전망 발표'; severity='높음'; channel='성장·물가·금리 전망'
        elif 'stress test' in title.lower():
            label='연준 은행 스트레스테스트 관련 발표'; severity='주의'; channel='은행 자본·대출 공급'
        elif 'resolution plan' in title.lower():
            label='연준 은행 정리계획 관련 발표'; severity='주의'; channel='금융안정·은행 규제'
        elif 'approval' in title.lower():
            label='연준 금융기관 승인 공시'; severity='관찰'; channel='해당 금융기관·규제'
        else:
            label='연준 공식 발표'; severity='관찰'; channel='본문 확인 후 영향 판단'
        out.append({'id':'fed-'+hashlib.sha256(url.encode()).hexdigest()[:14], 'title':label,'original_title':title, 'at':iso(published), 'published_at':iso(published), 'first_seen_at':iso(now), 'fetched_at':iso(now), 'available_at':iso(now), 'url':url, 'source_id':'fed_news', 'severity':severity, 'scope':'글로벌시장', 'channel':channel, 'state':'새로 등장','classification':'확인된 사실', 'summary':'공식 발표가 존재함을 확인했습니다. 가격·수급의 사건 반응과 인과관계는 아직 검증되지 않았습니다.', 'counter':'동시 뉴스·선반영·시장 전체 움직임을 분리해야 합니다.', 'reaction_status':'시장 반응 미검증'})
    for row in out:row['fetched_at']=client.received_at(feed_url)
    return sorted(out,key=lambda r:r['at'],reverse=True)[:20]


def sec_filings(client,now,watchlist):
    tickers=json.loads(client.get('https://www.sec.gov/files/company_tickers.json',ttl=86400))
    mapping={r['ticker']:r for r in tickers.values()}
    out=[];errors=[];covered=[]
    for symbol in watchlist:
        company=mapping.get(symbol)
        if not company:
            errors.append(symbol+': 공식 종목 매핑 없음');continue
        try:
            import time as rate_timer
            rate_timer.sleep(0.15)
            document_url=f"https://data.sec.gov/submissions/CIK{company['cik_str']:010}.json"
            doc=json.loads(client.get(document_url,ttl=1800))
            recent=doc['filings']['recent'];covered.append(symbol)
            for i,form in enumerate(recent['form']):
                if form not in ('8-K','8-K/A','10-Q','10-K','6-K'):
                    continue
                accepted=recent.get('acceptanceDateTime',[None]*len(recent['form']))[i]
                if not accepted:
                    continue
                dt=parse_time(accepted)
                if dt > now or dt < now-timedelta(days=14):
                    continue
                accession=recent['accessionNumber'][i]
                primary=recent['primaryDocument'][i]
                items=recent.get('items',['']*len(recent['form']))[i]
                earnings='2.02' in [x.strip() for x in str(items).split(',')]
                label='실적 관련 주요사건 공시' if earnings else {'8-K':'주요사건 공시','8-K/A':'주요사건 정정공시','10-Q':'분기보고서','10-K':'연차보고서','6-K':'외국기업 공시'}[form]
                url=f"https://www.sec.gov/Archives/edgar/data/{company['cik_str']}/{accession.replace('-','')}/{primary}"
                out.append({'id':'sec-'+accession,'ticker':symbol,'company':company['title'],'title':f'{symbol} {label}','form':form,'at':iso(dt),'published_at':iso(dt),'first_seen_at':iso(now),'available_at':iso(now),'fetched_at':iso(now),'source_id':'sec','url':url,'state':'새로 등장','severity':'주의','scope':'기업','channel':'기업 실적·재무·사업 변화 가능성','classification':'확인된 사실','summary':'SEC 공시 접수와 서식'+('·실적 항목(2.02)' if earnings else '')+'을 확인했습니다. 호재·악재 방향과 실제 가격 반응은 본문·시세 검증 전 미확정입니다.','counter':'공시 접수 자체가 상승·하락 원인이나 실적 발표 예정시간을 뜻하지 않습니다.','reaction_status':'시장 반응 미검증'})
            for row in out:
                if row.get('ticker')==symbol:row['fetched_at']=client.received_at(document_url)
        except (SourceError,KeyError,ValueError,TypeError):
            errors.append(symbol+': 공시 수신·스키마 확인 실패')
    if not covered:
        raise SourceError('관찰기업의 SEC 공시 수신 실패')
    return sorted(out,key=lambda r:r['at'],reverse=True)[:30],covered,errors


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None


def finra_margin(client,now):
    url='https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics'
    parser=TableParser();parser.feed(client.get(url,ttl=21600))
    out=[]
    for cells in parser.rows:
        if len(cells)<4 or not re.fullmatch(r'[A-Z][a-z]{2}-\d{2}',cells[0]):
            continue
        day=datetime.strptime(cells[0],'%b-%y').strftime('%Y-%m')
        vals=[number(c) for c in cells[1:4]]
        if None not in vals:
            out.append({'month':day,'debitUSDMillion':vals[0],'cashCreditUSDMillion':vals[1],'marginCreditUSDMillion':vals[2],'source_id':'finra','available_at':iso(now),'fetched_at':iso(now),'frequency':'월별','unit':'백만 달러'})
    if not out:raise SourceError('FINRA 통계 표 파싱 실패')
    return sorted(out,key=lambda r:r['month'])
