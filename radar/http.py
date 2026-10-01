"""Small, bounded HTTP client. Raw responses are private and never published."""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class SourceError(RuntimeError):
    pass


class HttpClient:
    def __init__(self, cache_dir, now=None):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.now = now or datetime.now(timezone.utc)
        self.calls = 0
        self.receipt_times = {}

    def received_at(self,url):
        value=self.receipt_times.get(url,self.now)
        return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')

    def get(self, url, ttl=0, headers=None, max_bytes=8_000_000):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / (key + '.json')
        if ttl and path.exists():
            try:
                cached = json.loads(path.read_text())
                age = self.now.timestamp() - cached['timestamp']
                if 0 <= age < ttl:
                    self.receipt_times[url]=datetime.fromtimestamp(cached['timestamp'],timezone.utc)
                    return cached['body']
            except (ValueError, KeyError, OSError):
                pass
        body = self.request(url, headers=headers, max_bytes=max_bytes)
        self.receipt_times[url]=self.now
        if ttl:
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'timestamp': self.now.timestamp(), 'body': body}))
            tmp.replace(path)
        return body

    def request(self, url, headers=None, data=None, max_bytes=8_000_000):
        request_headers = {'User-Agent': os.getenv('SEC_USER_AGENT') or 'OvernightMarketRadar/1.0 research github.com/juhwan7', 'Accept': '*/*'}
        request_headers.update(headers or {})
        payload = json.dumps(data).encode() if data is not None else None
        if payload is not None:
            request_headers['Content-Type'] = 'application/json'
        for attempt in range(2):
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers=request_headers, data=payload)
                with urllib.request.urlopen(req, timeout=18) as response:
                    body = response.read(max_bytes + 1)
                    if len(body) > max_bytes:
                        raise SourceError('응답 크기 제한 초과')
                    return body.decode('utf-8-sig')
            except urllib.error.HTTPError as exc:
                # Never include a URL with API keys or raw response bodies in logs.
                if exc.code not in (429, 500, 502, 503, 504) or attempt:
                    raise SourceError(f'HTTP {exc.code}') from None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt:
                    raise SourceError('연결 실패 또는 응답 시간 초과') from None
            time.sleep(0.5)
        raise SourceError('수신 실패')
