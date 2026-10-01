# overnight-market-radar

국내 종가베팅의 실제 매수 시점부터 다음 정규장 예정 매도까지 위험을 관찰하는 한국어 웹페이지입니다. 자동 주문 기능은 없습니다. **현재는 국내 장중 시세·선물·환율·신용 통계가 미연결이므로 판단 보류·후보 0개가 정상입니다.**

실제 연결된 공식 자료: 미국 재무부 일별 만기별 국채금리, BLS 경제 발표 일정, 연준 FOMC 날짜·공식 발표 RSS, SEC EDGAR 관찰기업 공시 메타데이터. FOMC 날짜는 공식, 정책발표 14시 ET는 별도 검증 전 통상시간 적용입니다. 금리와 공시 접수는 장중 거래대금·실제 순유입·실적 발표 예정시간을 대체하지 않습니다.

공개 URL: **미배포·미검증**. 예상 주소 `https://juhwan7.github.io/overnight-market-radar/`는 공개 검증 전 완료 주소가 아닙니다.

## 실행

Python 3.12 이상(외부 Python 패키지 불필요), Node 24, npm 잠금파일 사용.

```sh
python -m unittest discover -s tests/radar -v
python -m radar.pipeline
python -m radar.verify
npm ci --ignore-scripts
npm run build
python -m radar.package
python -m http.server 8765 --directory dist
```

`src/data.json`은 공개 허용 스냅샷, `.private/`는 공개하지 않는 원자료·인증 캐시, `data/`는 실제 운영·판단·브리핑 이력, `public/radar-manifest.json`은 배포 식별자입니다. 테스트 자료는 `tests/radar`에만 있습니다. 운영 스냅샷에 테스트 종목·수치를 넣지 않습니다.

## GitHub 설정

1. 공개 저장소 `overnight-market-radar`를 만들고 README 초기화로 기본 브랜치 `main`을 생성합니다. 이미 있으면 최신 `main`을 기준으로 병합합니다.
2. 코드 업로드 후 Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 선택합니다.
3. Actions의 `Market radar collect, verify and publish`를 실행합니다. `.github/workflows/radar.yml`은 10분 목표 예약, 수집·검증·이력 저장·빌드·Pages 업로드·배포·공개 HTTP 검증을 같은 실행에서 처리합니다.
4. `Verify public URL and exact data snapshot`이 실제 페이지/JSON/manifest의 해시, commit, 시각을 확인한 로그를 검사합니다. Actions가 녹색이라는 것만으로 화면 완료를 주장하지 않습니다.

`GITHUB_TOKEN` 자동 커밋으로 다른 워크플로우가 실행될 것이라고 가정하지 않습니다. 기본 브랜치 push를 사용자가 동시에 변경하면 안전하게 실패합니다. 강제 push·무한 재시도는 하지 않습니다. 단일 concurrency group, 오래된 스냅샷 덮어쓰기 차단, 실행 8분 제한을 사용합니다.

## 문서

- [모든 요구사항 상태](docs/project/status.md)
- [데이터·공개 권한·사용자 도움](docs/project/setup.md)
- [수식·분석 범위·시점 보존](docs/project/methodology.md)
- [운영·예약·비용·장애·남은 작업](docs/project/operations.md)
- 제공기관별 구조화 등록부: `config/sources.json`

## 사실과 해석

`확인된 사실 / 근거가 있는 해석 / 조건부 시나리오 / 확인되지 않음`을 구분합니다. `거래 집중 / 투자자군 순매수 / 설정·환매 흐름 / 상대강도 선호 / 자산 이동 가설`은 서로 다른 측정입니다. 자료 실패·미발표·미확보는 실제 0이 아닙니다. 낮은 위험이나 확률로 바꾸지 않습니다.

KRX API 약관의 제3자 제공 제한, 브로커/거래소 시세 재표시 권한을 확인하기 전 공개 수집을 켜지 않습니다. 비공식 Yahoo 시세를 무단 기본 공급자로 사용하지 않습니다. 보유종목 메모는 브라우저 로컬 저장만 합니다.
