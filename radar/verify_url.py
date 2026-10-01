"""Completion needs public HTTP and matching build/code/data, not Actions green."""
import hashlib,json,os,time,urllib.request
from .http import SourceError

def fetch(base,name):
    with urllib.request.urlopen(base.rstrip('/')+'/'+name+'?check='+str(time.time_ns()),timeout=15) as r:
        if r.status!=200:raise SourceError('공개 URL HTTP 실패')
        return r.read()

def verify(base,expected):
    manifest=json.loads(fetch(base,'radar-manifest.json'));data=fetch(base,'radar-data.json');html=fetch(base,'index.html')
    assert manifest['snapshot_id']==expected,'공개 URL에 최신 스냅샷 미반영'
    assert hashlib.sha256(data).hexdigest()==manifest['snapshot_sha256'],'데이터 바이트 해시 불일치'
    assert hashlib.sha256(html).hexdigest()==manifest['html_sha256'],'화면 빌드 해시 불일치'
    snapshot=json.loads(data)
    assert snapshot['radar']['snapshot_id']==expected
    assert snapshot['radar']['source_commit']==manifest['source_commit']
    assert snapshot['generatedAt']==manifest['generated_at']
    return manifest

if __name__=='__main__':
    base=os.environ['RADAR_PUBLIC_URL'];expected=os.environ['RADAR_EXPECTED_SNAPSHOT']
    for attempt in range(5):
        try:
            result=verify(base,expected)
            print(json.dumps({'url':base,'snapshot':expected,'code_commit':result['source_commit'],'deploy_commit':result['deploy_commit'],'generated_at':result['generated_at'],'verification':'공개 HTTP·HTML·데이터 해시 일치'},ensure_ascii=False));break
        except Exception:
            if attempt==4:raise SystemExit('공개 URL·최신 스냅샷·빌드 검증 실패. 배포 완료로 처리할 수 없습니다.')
            time.sleep(min(4*2**attempt,30))
