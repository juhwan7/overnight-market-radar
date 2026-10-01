# 사용자 도움과 데이터 연결

도움 요청은 이 문서와 운영 화면의 동일 `config/sources.json` 식별자로 모읍니다. 계정이나 API 키를 받았다는 사실만으로 해결 처리하지 않습니다. **실제 수신·필드·시각·세션·지연·공개 권한·공개 URL 검증** 뒤 상태를 바꿉니다.

|필요 기능|필요 이유·정확한 작업|Secret|예상 비용·완료 전 대안|
|---|---|---|---|
|GitHub 저장소 생성·Pages 설정|GitHub 연결 도구에 생성·Pages 관리 기능이 없음. 저장소를 README 포함 공개로 생성 후 Pages Source=GitHub Actions|없음|표준 공개 러너는 GitHub 무료 범위. 생성 전 소스·로컬 화면 제공|
|국내 시세 KIS|[공식 안내](https://apiportal.koreainvestment.com/intro). 계정·앱 키와 조회 시세 권한 신청. 공개 재표시 별도 확인|`KIS_APP_KEY`, `KIS_APP_SECRET`|권한·상품별 확인. 연결 전 후보 0개|
|국내·미국·선물·환율·아시아·자산 피드|공개 표시를 허가받은 HTTPS 구조화 공급자와 계약. 아래 스키마로 제공. 실제 월물·시세시각 필수|`MARKET_FEED_URL`|상품별 유료 가능. 미확보를 계속 표시|
|SEC 접속 식별|[SEC 공식 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), 연락 가능한 프로젝트 User-Agent 설정|`SEC_USER_AGENT`|무료. 기본 식별자로 제한 수집·접속 거절 시 장애 표시|
|국내 신용·미수·실제 반대매매|[금투협](https://freesis.kofia.or.kr/) 제공 정의·공표일·자동수집·공개 허용 범위 확인 후 공식 자료 피드 연결|`MARKET_FEED_URL`|제공 조건 미확인. 통계 미확보|
|DART 기업 위험|[OpenDART](https://opendart.fss.or.kr/) 키 신청 및 공시·기업행사 상세 파서 추가 필요|향후 `DART_API_KEY`|일반 무료 API·조건 확인. 현재 개별 국내 위험 미검증|
|ECOS 일별 환율|[ECOS](https://ecos.bok.or.kr/api/) 키·통계표·단위·공표시각 검증과 어댑터 추가 필요|향후 `ECOS_API_KEY`|일반 무료 통계. 장중 원달러 대용으로 쓰지 않음|
|펀드·ETF·MMF 흐름|운용사 공식 설정·환매/순유입 데이터 계약·보관 권한 확인|`MARKET_FEED_URL`|상품별. NAV 변화·거래대금을 순유입으로 대체하지 않음|

키는 저장소 Settings → Secrets and variables → Actions에만 저장합니다. 공개 브라우저 코드·JSON·로그·문서에 계좌와 비밀키를 넣지 않습니다. KIS 응답은 기본 `.private` 보관만 하며 `config/radar.json`의 `publication_approvals.kis=true`는 **재표시 허가 근거가 있을 때만** 설정합니다. 현 가격 어댑터는 수신시각을 실제 시세시각으로 바꾸지 않기 때문에 연결 후에도 그 필드를 검증하기 전 후보는 보류됩니다.

KRX [공식 약관](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp)의 제3자 제공 제한을 고려해 기본 수집·공개 어댑터를 활성화하지 않습니다. 서비스별 신청·권한·호출 한도는 [KRX 포털](https://openapi.krx.co.kr/)에서 확인합니다.

## 허가 피드 스키마

`schema_version: 1`, `public_display_permission: true`, `provider`, `documentation_url` 필수입니다. 이 플래그는 계약상 허가를 받았다는 운영자 확인이며 법적 허가를 도구가 자동 검증한다는 뜻은 아닙니다.

범주 배열: `market_kr`, `market_us`, `futures`, `fx`, `asia`, `assets`, `leverage_kr`, `investor_flows`, `fund_flows`, `daily_bars`, `earnings`. 지원되는 필드만 공개합니다. 범주가 없으면 미확보입니다. 빈 배열을 0 흐름으로 바꾸지 않습니다.

각 레코드 공통: `id`, `source_url`(공개 HTTPS 링크), `observed_at`, `published_at`, `available_at`(타임존 포함 ISO8601), `unit`, `currency`, `frequency`, `market`, `venue`, `session`. 수신은 현재시각, 관측·발표·이용 가능 시각은 공급자 필드 그대로 보존해야 합니다. 미래 관측·미래 이용 가능 시각이나 필수값 누락은 제외합니다.

시세 추가: `ticker`, `name`, `price`, `turnover`, `volume`, `sector`, `universe`, `instrument_type`, `dayChangePct`, `high`, `low`, `closePosition`, `corporate_actions_checked`. 주식 거래대금은 실제 공급자 측정값이어야 하며 종가×거래량 추정치가 아닙니다. `universe`는 부분 범위를 명시합니다.

선물 추가: `contract`, `expiry`, `exchange`, `underlying`, `delay_status`; 롤오버·연속선물 조정·국내 마감 시각 기준가격은 별도 필드와 검증 필요합니다. `fund_flows.measurement`는 `공식 순유입·순유출` 또는 `공식 설정·환매`만 허용합니다. 신용은 `reference_date`, `definition`, `denominator_definition` 필수입니다.

인증 주소는 Secret에 넣고 주소·응답 원문을 로그에 출력하지 않습니다. 원시 URL을 공개 레코드 `source_url`로 넣으면 안 됩니다. 인증 공급자 연결 후 `python -m radar.pipeline`, `python -m radar.verify`와 실제 데이터 표 검증을 수행합니다.
