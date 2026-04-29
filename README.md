# Quant Data Platform Prototype

무료 기반 미국 주식 백테스트 데이터 파이프라인 프로토타입입니다.

## 스택
- Sources: `SEC + Alpha Vantage + yfinance + Tiingo + FRED`
- Storage: `PostgreSQL + MinIO`
- DB Web UI: `pgAdmin`
- Transform: `dbt-postgres`
- Orchestration: `Airflow`
- Runtime: `Docker Compose`
- Python packaging/runtime: `uv`

## API Key 준비
아래 값들을 준비합니다.

- `ALPHAVANTAGE_API_KEY`
  - 발급: <https://www.alphavantage.co/support/#api-key>
- `TIINGO_API_KEY`
  - 발급: <https://api.tiingo.com/account/api/token>
  - 안내: <https://www.tiingo.com/kb/article/where-to-find-your-tiingo-api-token/>
- `FRED_API_KEY`
  - 발급: <https://fredaccount.stlouisfed.org/apikeys>
- `SEC_USER_AGENT`
  - 예시: `YourName your@email.com`
  - 참고: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- `yfinance`
  - 별도 API 키는 없습니다.
  - 용도: 장기 history 백필 전용

`.env.example`를 복사해 `.env`를 만들고 값을 채웁니다.

## 빠른 시작
1. `cp .env.example .env`
2. `.env`에 API 키와 User-Agent를 입력
3. `docker compose up --build airflow-init`
4. `docker compose up -d postgres minio pgadmin airflow-webserver airflow-scheduler`
5. Airflow UI 접속: <http://localhost:8080>
6. MinIO Console 접속: <http://localhost:9001>
7. pgAdmin 접속: <http://localhost:5050>
8. PostgreSQL host 포트: `localhost:55432`

pgAdmin 기본 로그인 값:

- `PGADMIN_DEFAULT_EMAIL`
- `PGADMIN_DEFAULT_PASSWORD`

PostgreSQL 서버는 `quant-postgres` 이름으로 자동 등록됩니다.

## 테스트
로컬 단위 테스트:

```bash
uv run pytest
```

키가 준비된 뒤 live integration 테스트:

```bash
ALPHAVANTAGE_API_KEY=... TIINGO_API_KEY=... FRED_API_KEY=... SEC_USER_AGENT="YourName your@email.com" uv run pytest -m integration
```

Docker 구성 검증:

```bash
docker compose config
```

## 백테스트 웹 실행
권장 경로는 Docker입니다.

Docker로 실행:

```bash
docker compose up -d postgres backtest-web
```

- 앱: <http://localhost:8000/backtest>
- readiness: <http://localhost:8000/healthz>

로컬 `uv run`으로 실행할 때는 네이티브 Postgres와 충돌하지 않도록 compose Postgres 포트를 명시적으로 사용합니다.

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 uv run uvicorn quant_data_platform.web.app:app --reload
```

## DAG
- `backfill_market_data`
- `backfill_fundamentals`
- `daily_incremental_pipeline`
- `build_liquidity_universe`

## 소스 역할
- `Alpha Vantage`: listing status, symbol overview
- `yfinance`: 장기 history 백필, 배당, 분할 기반 기업행위
- `Tiingo`: 일별 incremental 가격 업데이트
- `SEC`: filings, companyfacts
- `FRED`: risk-free series

## 현재 권장 운영 방식
- `build_liquidity_universe`와 `backfill_market_data`는 `yfinance` 기반 장기 history를 사용합니다.
- `daily_incremental_pipeline`의 시장 데이터 증분은 `Tiingo`를 사용합니다.
- dbt의 `stg_daily_prices`는 `Tiingo`와 `yfinance_history`가 겹치는 날짜에서 `Tiingo`를 우선합니다.

## dbt 모델
- `stg_*`: 원천 정규화
- `int_*`: point-in-time / total-return / universe 중간계층
- `mart_*`: 전략별 백테스트 입력 마트

## Mart Coverage Audit
최근 mart coverage를 점검할 때는 아래 명령을 사용합니다.

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 uv run python -m quant_data_platform.cli audit-mart-coverage --cohort us_liquidity_700_v1
```

JSON이 필요하면:

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 uv run python -m quant_data_platform.cli audit-mart-coverage --cohort us_liquidity_700_v1 --format json
```

리포트에는 아래 내용이 포함됩니다.

- `stg/int/mart` row 수, 날짜 범위, distinct entity 수
- strategy mart의 `cohort` 분포
- 최신 유니버스 기준 `stable_id_or_cik` 미매핑 / PIT fundamentals 미보유 심볼
- 최신 `value_quality` factor null profile
- 최근 월별 fully-eligible symbol 수

## Full-Universe Backfill Runbook
mart coverage를 실제로 늘릴 때는 아래 순서를 권장합니다.

1. 사전 audit 실행
2. full-universe fundamentals backfill
3. full-universe market refresh
4. universe rebuild
5. daily/dbt rebuild
6. 사후 audit 실행

Airflow 경로 예시:

```bash
docker compose exec airflow-webserver airflow dags trigger backfill_fundamentals --conf '{"full_universe": true, "mode": "full"}'
docker compose exec airflow-webserver airflow dags trigger backfill_market_data --conf '{"full_universe": true, "mode": "recent"}'
docker compose exec airflow-webserver airflow dags trigger build_liquidity_universe
docker compose exec airflow-webserver airflow dags trigger daily_incremental_pipeline
```

CLI 경로가 필요할 때는 `--full-universe` 플래그를 사용할 수 있습니다.

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 MINIO_ENDPOINT=http://127.0.0.1:9000 uv run python -m quant_data_platform.cli backfill-fundamentals --full-universe --mode full
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 MINIO_ENDPOINT=http://127.0.0.1:9000 uv run python -m quant_data_platform.cli backfill-market --full-universe --mode recent
```

SPY benchmark 백필/일일 갱신 메모:

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 MINIO_ENDPOINT=http://127.0.0.1:9000 uv run python -m quant_data_platform.cli backfill-market --symbols SPY --mode full
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 MINIO_ENDPOINT=http://127.0.0.1:9000 uv run python -m quant_data_platform.cli daily-incremental
```

- `SUPPORT_MARKET_SYMBOLS` 기본값은 `SPY,VT,IEF,SGOV,JPST`이며, 일반 공통주 유니버스와 별개로 시장 데이터 적재 대상에 항상 병합됩니다.
- `stg_benchmark_series`의 `SPY`는 `stg_daily_prices`의 최신 종목별 가격 스냅샷 전체를 사용하므로, 부분 recent 갱신 후에도 과거 이력이 유지됩니다.

주의:

- strategy mart는 여전히 `DBT_UNIVERSE_COHORT` 기준 cohort-clean 데이터를 기본 source로 사용합니다.
- full-universe backfill은 upstream coverage 확장 목적이며, backtest UI는 cohort-backed marts를 읽습니다.
