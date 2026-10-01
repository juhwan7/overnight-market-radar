import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from radar import pipeline
from radar.calendars import parse_time
from radar.http import SourceError
from radar.verify import validate

ROOT=Path(__file__).resolve().parents[2]
class PartialFailure(unittest.TestCase):
    def test_partial_failure_preserves_timestamp_and_fails_closed(self):
        previous=json.loads((ROOT/'src/data.json').read_text())
        now=parse_time(previous['generatedAt'])
        from datetime import timedelta
        now+=timedelta(minutes=10)
        old_rates=previous['queries']['rates']['rows']
        old_fomc=[r for r in previous['queries']['events']['rows'] if r['source_id']=='fomc']
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();(root/'src').mkdir()
            for name in ('radar.json','sources.json'):(root/'config'/name).write_bytes((ROOT/'config'/name).read_bytes())
            (root/'src/data.json').write_text(json.dumps(previous))
            with patch.object(pipeline,'ROOT',root),patch.dict('os.environ',{},clear=True),patch.object(pipeline.providers,'treasury',return_value=old_rates),patch.object(pipeline.providers,'bls_events',return_value=[]),patch.object(pipeline.providers,'fomc_events',side_effect=SourceError('테스트 전용 부분 장애')),patch.object(pipeline.providers,'fed_news',return_value=[]),patch.object(pipeline.providers,'sec_filings',return_value=([],['NVDA'],[])),contextlib.redirect_stdout(io.StringIO()):
                result=pipeline.run(now)
            self.assertTrue(validate(result));self.assertEqual(result['radar']['risk']['decision'],'판단 보류')
            self.assertEqual(result['queries']['rates']['rows'],old_rates)
            retained=[r for r in result['queries']['events']['rows'] if r['source_id']=='fomc']
            self.assertEqual(retained,old_fomc)
            self.assertEqual(result['radar']['source_states']['fomc']['status'],'수집 실패·마지막 정상 자료')
            self.assertIn('테스트 전용 부분 장애',result['queries']['operations']['rows'][-1]['failures'][0])
    def test_old_result_cannot_overwrite_new(self):
        with self.assertRaises(SourceError):pipeline.run(parse_time('2026-09-30T12:00:00Z'))
