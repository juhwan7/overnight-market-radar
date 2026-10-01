import copy,json,tempfile,unittest
from datetime import datetime,date,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from radar.calendars import session_for,holding_window,parse_time
from radar.analysis import turnover_concentration,choose_candidates,risk_assessment,empirical_gaps,rate_summary,safe_rows
from radar.metrics import intraday_activity,relative_strength,after_close_change,leverage_history,event_reaction
from radar.providers import parse_ics,fomc_events,number
from radar.feed import validate_feed
from radar.http import SourceError
from radar.verify import validate
ROOT=Path(__file__).resolve().parents[2]
NOW=parse_time('2026-10-01T06:20:00Z')
CONFIG=json.loads((ROOT/'config/radar.json').read_text())

def bar(**kw):
    r={'ticker':'005930','name':'검증용 보통주','market':'KR','venue':'KRX','currency':'KRW','observed_at':'2026-10-01T06:19:00Z','available_at':'2026-10-01T06:19:01Z','time_verified':True,'universe':'테스트 전용','turnover':20_000_000_000,'sector':'전자','instrument_type':'보통주','dayChangePct':2,'closePosition':0.9,'corporate_actions_checked':True};r.update(kw);return r
class Rules(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertIsNone(number(''));self.assertEqual(number('0'),0);self.assertIsNone(number('nan'))
    def test_same_time_denominator(self):
        r=turnover_concentration([bar(turnover=100),bar(ticker='x',sector='은행',turnover=100),bar(ticker='y',sector='은행',turnover=900,observed_at='2026-10-01T06:18:00Z')])
        now=[x for x in r if x['observed_at']=='2026-10-01T06:19:00Z'];self.assertEqual(sum(x['turnoverShare'] for x in now),1);self.assertTrue(all(x['denominator']==200 for x in now))
    def test_unverified_timestamp_not_aggregated(self):self.assertEqual(turnover_concentration([bar(observed_at=None)]),[])
    def test_currency_not_added(self):
        r=turnover_concentration([bar(),bar(market='US',currency='USD',venue='NASDAQ')]);self.assertEqual(len(r),2)
    def test_availability_cutoff(self):self.assertEqual(safe_rows([bar(available_at='2026-10-01T07:00:00Z')],NOW),[])
    def test_future_catalyst_does_not_select(self):
        issues=[{'ticker':'005930','classification':'확인된 사실','catalyst_verified':True,'available_at':'2026-10-01T07:00:00Z'}]
        selected,excluded=choose_candidates([bar()],issues,NOW,CONFIG,{'decision':'주의'});self.assertEqual(selected,[]);self.assertIn('촉매',excluded[0]['reasons'])
    def test_missing_critical_fails_closed(self):self.assertEqual(risk_assessment([],holding_window(NOW,CONFIG['calendar']),{},[],NOW)['decision'],'판단 보류')
    def test_stale_prices_excluded(self):
        selected,excluded=choose_candidates([bar(observed_at='2026-10-01T05:00:00Z')],[],NOW,CONFIG,{'decision':'주의'});self.assertFalse(selected);self.assertIn('지연',excluded[0]['reasons'])
    def test_rates_basis_points(self):
        r=rate_summary([{'date':'2026-09-29','maturity':'10년','yieldPct':5.26},{'date':'2026-09-30','maturity':'10년','yieldPct':5.29}]);self.assertEqual(r[0]['changeBp'],3)
    def test_kr_holiday_window(self):
        w=holding_window(parse_time('2026-10-02T06:20:00Z'),CONFIG['calendar']);self.assertEqual(w['next_day'],'2026-10-06');self.assertEqual(w['hours'],89.7)
    def test_unknown_calendar(self):self.assertIsNone(session_for(date(2027,1,4),'KRX',CONFIG['calendar'])['open'])
    def test_us_dst_and_early_close(self):
        c=CONFIG['calendar'];self.assertTrue(session_for(date(2026,10,1),'NYSE',c)['close'].endswith('20:00:00Z'));self.assertTrue(session_for(date(2026,11,27),'NYSE',c)['close'].endswith('18:00:00Z'))
    def test_ics_timezone_and_unfold(self):
        t='BEGIN:VEVENT\nUID:1\nSUMMARY:Employment Situation\nDTSTART;TZID=US-Eastern:20261002T083000\nEND:VEVENT'
        r=parse_ics(t,NOW);self.assertEqual(r[0]['at'],'2026-10-02T12:30:00Z')
    def test_fomc_markup(self):
        class Client:
            def get(self,*a,**k):return '<h4><a id="x">2026 FOMC Meetings</a></h4><div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">27-28</div>'
        r=fomc_events(Client(),NOW);self.assertEqual(r[0]['at'],'2026-10-28T18:00:00Z');self.assertEqual(r[0]['classification'],'조건부 시나리오')
    def test_intraday_not_compared_with_full_day(self):
        current=[bar(trade_date='2026-10-01',session='정규장',session_minute=380)]
        history=[bar(trade_date='2026-09-30',session='정규장',session_minute=390)]
        self.assertIsNone(intraday_activity(current,history,NOW,minimum=1)[0]['activity'])
    def test_relative_strength_aligned(self):
        self.assertIsNone(relative_strength(bar(return_basis='전일 종가'),bar(observed_at='2026-10-01T06:18:00Z',return_basis='전일 종가')))
    def test_rollover_excluded(self):
        a=bar(instrument='NQ',contract='NQZ6',expiry='2026-12',price=20000);b=bar(instrument='NQ',contract='NQH7',expiry='2027-03',price=19500,aligned_to_kr_close=True)
        self.assertIsNone(after_close_change(a,b)['changePct'])
    def test_leverage_sample_gate(self):
        r=bar(name='신용',unit='원',definition='잔고',denominator_definition='없음',reference_date='2026-10-01',value=100)
        self.assertIsNone(leverage_history([r],[],NOW)[0]['percentile'])
    def test_gap_sample_gate(self):self.assertIsNone(empirical_gaps([],NOW)['quantiles'])
    def test_minute_bars_not_daily_gaps(self):
        self.assertEqual(empirical_gaps([bar(open=100,close=100),bar(open=110,close=110)],NOW)['sample'],0)
    def test_feed_permission_required(self):
        with self.assertRaises(SourceError):validate_feed({'schema_version':1,'public_display_permission':False},NOW)
    def test_feed_future_rejected(self):
        d={'schema_version':1,'public_display_permission':True,'provider':'Test','documentation_url':'https://example.com','market_kr':[bar(available_at='2026-10-02T06:20:00Z')]};r,errors=validate_feed(d,NOW);self.assertFalse(r['market_kr']);self.assertTrue(errors)
    def test_public_snapshot_boundaries(self):self.assertTrue(validate(json.loads((ROOT/'src/data.json').read_text())))
    def test_production_does_not_include_test_rows(self):
        self.assertNotIn('검증용 보통주',(ROOT/'src/data.json').read_text())
    def test_github_pipeline_direct_deploy(self):
        y=(ROOT/'.github/workflows/radar.yml').read_text();self.assertIn('needs: collect',y);self.assertIn('python -m radar.verify_url',y);self.assertIn('cancel-in-progress: false',y);self.assertNotIn('pull_request_target',y)
if __name__=='__main__':unittest.main()
