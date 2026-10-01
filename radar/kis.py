"""Read-only KIS adapters checked against official open-trading-api samples.

No account number or order permission is needed by this code. Actual access,
instrument fields, delay and public display entitlement still require validation.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from .calendars import KST, iso
from .http import SourceError
from .providers import number

BASE='https://openapi.koreainvestment.com:9443'


class KisClient:
    def __init__(self,client,now,cache_dir):
        self.client=client;self.now=now;self.key=os.getenv('KIS_APP_KEY');self.secret=os.getenv('KIS_APP_SECRET')
        self.token_file=Path(cache_dir)/'kis-token.json'
        if not self.key or not self.secret:
            raise SourceError('KIS_APP_KEY·KIS_APP_SECRET 연결 필요')

    def token(self):
        if self.token_file.exists():
            try:
                data=json.loads(self.token_file.read_text())
                if data['expires_at'] > self.now.timestamp()+1800:
                    return data['access_token']
            except (KeyError,ValueError,OSError):pass
        data=json.loads(self.client.request(BASE+'/oauth2/tokenP',data={'grant_type':'client_credentials','appkey':self.key,'appsecret':self.secret}))
        if not data.get('access_token'):raise SourceError('KIS 토큰 발급 실패')
        self.token_file.write_text(json.dumps({'access_token':data['access_token'],'expires_at':self.now.timestamp()+int(data.get('expires_in',0))}))
        os.chmod(self.token_file,0o600)
        return data['access_token']

    def get(self,path,tr_id,params):
        time.sleep(0.12)
        headers={'authorization':'Bearer '+self.token(),'appkey':self.key,'appsecret':self.secret,'tr_id':tr_id,'custtype':'P'}
        doc=json.loads(self.client.request(BASE+path+'?'+urlencode(params),headers=headers))
        if doc.get('rt_cd') != '0':raise SourceError('KIS API 응답 오류·시세 권한 확인 필요')
        return doc

    def domestic(self,config):
        market=config['market_code']
        rank=self.get('/uapi/domestic-stock/v1/quotations/volume-rank','FHPST01710000',{
          'FID_COND_MRKT_DIV_CODE':market,'FID_COND_SCR_DIV_CODE':'20171','FID_INPUT_ISCD':'0000',
          'FID_DIV_CLS_CODE':'1','FID_BLNG_CLS_CODE':'3','FID_TRGT_CLS_CODE':'111111111',
          'FID_TRGT_EXLS_CLS_CODE':'1111111111','FID_INPUT_PRICE_1':'','FID_INPUT_PRICE_2':'','FID_VOL_CNT':'','FID_INPUT_DATE_1':''})
        rows=[]
        for row in rank.get('output',[])[:config['max_detail_stocks']]:
            code=row.get('mksc_shrn_iscd')
            if not code:continue
            doc=self.get('/uapi/domestic-stock/v1/quotations/inquire-price','FHKST01010100',{'FID_COND_MRKT_DIV_CODE':market,'FID_INPUT_ISCD':code})
            q=doc['output'];price=number(q.get('stck_prpr'));high=number(q.get('stck_hgpr'));low=number(q.get('stck_lwpr'))
            # Price endpoint has no reliably verified quote timestamp in this adapter.
            # Receipt time is not relabelled as observation time; candidates fail closed.
            rows.append({'ticker':code,'name':row.get('hts_kor_isnm',code),'market':'KR','venue':market,
                'sector':q.get('bstp_kor_isnm') or '업종 미확인','currency':'KRW','price':price,
                'high':high,'low':low,'dayChangePct':number(q.get('prdy_ctrt')),
                'turnover':number(q.get('acml_tr_pbmn')),'volume':number(q.get('acml_vol')),
                'closePosition':(price-low)/(high-low) if None not in (price,high,low) and high>low else None,
                'source_id':'kis','observed_at':None,'fetched_at':iso(self.now),'available_at':iso(self.now),
                'session':'정규장·현재 조회값(실제 시세시각 확인 필요)','instrument_type':'보통주 조회조건',
                'time_verified':False,'universe':'거래대금 순위 응답 중 상세 조회 범위','investor_net':None})
        if not rows:raise SourceError('국내 거래대금 순위 레코드 없음')
        return rows

    def intraday(self,ticker,market='J'):
        doc=self.get('/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice','FHKST03010200',{
          'FID_COND_MRKT_DIV_CODE':market,'FID_INPUT_ISCD':ticker,'FID_INPUT_HOUR_1':self.now.astimezone(KST).strftime('%H%M%S'),
          'FID_PW_DATA_INCU_YN':'Y','FID_ETC_CLS_CODE':''})
        rows=[]
        for bar in doc.get('output2',[]):
            day=bar.get('stck_bsop_date');clock=bar.get('stck_cntg_hour')
            if not day or not clock:continue
            observed=datetime.strptime(day+clock,'%Y%m%d%H%M%S').replace(tzinfo=KST)
            vals={k:number(bar.get(v)) for k,v in [('open','stck_oprc'),('high','stck_hgpr'),('low','stck_lwpr'),('close','stck_prpr'),('volume','cntg_vol')]}
            if any(vals[k] is None for k in ('open','high','low','close')):continue
            rows.append(dict(vals,ticker=ticker,observed_at=iso(observed),available_at=iso(self.now),source_id='kis',venue=market,currency='KRW'))
        return sorted(rows,key=lambda r:r['observed_at'])

    def investor(self,ticker,market='J'):
        doc=self.get('/uapi/domestic-stock/v1/quotations/inquire-investor','FHKST01010900',{'FID_COND_MRKT_DIV_CODE':market,'FID_INPUT_ISCD':ticker})
        return [{'ticker':ticker,'date':r.get('stck_bsop_date'),'foreignNetQty':number(r.get('frgn_ntby_qty')),
          'institutionNetQty':number(r.get('orgn_ntby_qty')),'individualNetQty':number(r.get('prsn_ntby_qty')),
          'unit':'주','source_id':'kis','available_at':iso(self.now),'frequency':'제공 응답 기준일별'} for r in doc.get('output',[])]

