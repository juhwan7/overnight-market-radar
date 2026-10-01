"""Official calendar overrides. Unknown coverage fails closed."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')


def iso(dt):
    return dt.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def session_for(day, market, config):
    info = config['markets'][market]
    year = str(day.year)
    covered = year in info['verified_years'] or any(r['from'] <= day.isoformat() <= r['to'] for r in info.get('verified_ranges', []))
    if not covered:
        return {'date': day.isoformat(), 'status': '달력 확인 필요', 'open': None, 'close': None}
    if day.weekday() >= 5 or day.isoformat() in info['holidays']:
        return {'date': day.isoformat(), 'status': '휴장', 'open': None, 'close': None}
    tz = ZoneInfo(info['timezone'])
    override = info.get('sessions', {}).get(day.isoformat(), {})
    opening = override.get('open', info['open'])
    closing = override.get('close', info['close'])
    return {'date': day.isoformat(), 'status': '거래일',
            'open': iso(datetime.combine(day, time.fromisoformat(opening), tz)),
            'close': iso(datetime.combine(day, time.fromisoformat(closing), tz))}


def next_session(now, market, config, include_today=True):
    tz = ZoneInfo(config['markets'][market]['timezone'])
    day = now.astimezone(tz).date()
    for offset in range(15):
        if offset == 0 and not include_today:
            continue
        item = session_for(day + timedelta(days=offset), market, config)
        if item['status'] == '달력 확인 필요':
            return item
        if item['open'] and (offset > 0 or parse_time(item['close']) > now):
            return item
    return {'status': '달력 확인 필요', 'date': None, 'open': None, 'close': None}


def market_clock(now, market, config):
    tz = ZoneInfo(config['markets'][market]['timezone'])
    item = session_for(now.astimezone(tz).date(), market, config)
    if item['status'] == '달력 확인 필요':
        return dict(item, phase='달력 확인 필요')
    if item['status'] == '휴장':
        return dict(item, phase='휴장')
    if now < parse_time(item['open']):
        phase = '정규장 전'
    elif now < parse_time(item['close']):
        phase = '정규장 진행'
    else:
        phase = '정규장 종료'
    return dict(item, phase=phase)


def holding_window(now, config, sell_time='09:00'):
    next_kr = next_session(now, 'KRX', config)
    if next_kr.get('status') != '거래일':
        return {'start': iso(now), 'end': None, 'hours': None, 'next_day': next_kr.get('date'), 'status': '달력 확인 필요'}
    end = datetime.combine(date.fromisoformat(next_kr['date']), time.fromisoformat(sell_time), KST)
    if end <= now:
        next_kr = next_session(now, 'KRX', config, include_today=False)
        if not next_kr.get('open'):
            return {'start': iso(now), 'end': None, 'hours': None, 'next_day': next_kr.get('date'), 'status': '달력 확인 필요'}
        end = datetime.combine(date.fromisoformat(next_kr['date']), time.fromisoformat(sell_time), KST)
    return {'start': iso(now), 'end': iso(end), 'hours': round((end-now).total_seconds()/3600, 1), 'next_day': next_kr['date'], 'status': '확인'}
