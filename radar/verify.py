"""Validate the public boundary independently from collection."""
import json,re
from pathlib import Path
from .calendars import parse_time

ROOT=Path(__file__).resolve().parents[1]

def validate(snapshot):
    assert snapshot['surface']=='dashboard'
    assert snapshot['radar']['snapshot_id']
    cutoff=parse_time(snapshot['generatedAt'])
    for key,query in snapshot['queries'].items():
        assert isinstance(query['rows'],list) and query['source']['links']
        if key in ('rates','events','issues','markets','flows','leverage'):
            for row in query['rows']:
                assert row.get('source_id') and row.get('available_at'),key
                assert parse_time(row['available_at'])<=cutoff,'Future availability leaked'
                if key=='markets' and not (row.get('time_verified') and row.get('observed_at')):
                    assert row.get('source_id')=='kis' and row.get('time_verified') is False and row.get('observed_at') is None,'Unverified quote time'
                    assert snapshot['radar']['risk']['decision']=='판단 보류','Unknown KIS timestamp used for decision'
    risk=snapshot['radar']['risk']
    if risk['missing']:assert risk['decision']=='판단 보류'
    assert risk['probability'] is None
    for row in snapshot['radar']['candidates']:
        assert row['market']=='KR' and row['time_verified'] and row['corporate_actions_checked']
    assert len(snapshot['radar']['candidates'])<=5
    text=json.dumps(snapshot)
    assert not re.search(r'"(?:access_token|appsecret|account_number|KIS_APP_SECRET)"\s*:',text),'Private credentials in public snapshot'
    assert all(query['rows'] is not None for query in snapshot['queries'].values())
    return True

if __name__=='__main__':
    snapshot=json.loads((ROOT/'src/data.json').read_text());validate(snapshot)
    print('공개 스냅샷·시점·누락값·후보 보류 검증 통과')
