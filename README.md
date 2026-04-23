# Quant Data Platform Prototype

무료 기반 미국 주식 백테스트 데이터 파이프라인 프로토타입입니다.

## 스택
- Sources: `SEC + Alpha Vantage + Tiingo + FRED`
- Storage: `PostgreSQL + MinIO`
- DB Web UI: `pgAdmin`
- Transform: `dbt-postgres`
- Orchestration: `Airflow`
- Runtime: `Docker Compose`
- Python packaging/runtime: `uv`

## API Key 준비
아래 세 값이 필요합니다.

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

`.env.example`를 복사해 `.env`를 만들고 값을 채웁니다.

## 빠른 시작
1. `cp .env.example .env`
2. `.env`에 API 키와 User-Agent를 입력
3. `docker compose up --build airflow-init`
4. `docker compose up -d postgres minio pgadmin airflow-webserver airflow-scheduler`
5. Airflow UI 접속: <http://localhost:8080>
6. MinIO Console 접속: <http://localhost:9001>
7. pgAdmin 접속: <http://localhost:5050>

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

## DAG
- `backfill_market_data`
- `backfill_fundamentals`
- `daily_incremental_pipeline`

## 소스 역할
- `Alpha Vantage`: listing status, symbol overview
- `Tiingo`: 장기 일별 가격, 배당, 분할 기반 기업행위
- `SEC`: filings, companyfacts
- `FRED`: risk-free series

## dbt 모델
- `stg_*`: 원천 정규화
- `int_*`: point-in-time / total-return / universe 중간계층
- `mart_*`: 전략별 백테스트 입력 마트
