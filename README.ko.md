# 퀀트 데이터 플랫폼

무료 또는 저비용 데이터 소스를 활용해 미국 주식 리서치와 백테스트용 데이터 플랫폼을 구성하는 오픈소스 프로토타입입니다.

이 프로젝트는 시장 데이터, 재무 데이터, 매크로 데이터, 공시 데이터를 수집하고 point-in-time 리서치 마트로 변환한 뒤 Airflow, dbt, PostgreSQL, MinIO, FastAPI 웹 인터페이스로 검토할 수 있게 만드는 데 초점을 둡니다.

> 리서치와 학습 목적의 프로젝트입니다. 투자 조언이나 실거래 성과를 보장하지 않습니다.

English documentation: [README.md](README.md)

## 주요 기능

- SEC, Alpha Vantage, yfinance, Tiingo, FRED 기반 미국 주식 데이터 수집
- PostgreSQL 구조화 데이터 저장과 MinIO 객체 저장
- dbt staging, intermediate, mart 모델 생성
- 유동성 기반 주식 유니버스와 SPY 같은 보조 시장 심볼 관리
- 백필, 유니버스 생성, 일일 증분 업데이트용 Airflow DAG 제공
- 백테스트, 현재 포트폴리오, Alpaca paper trading 검토용 FastAPI 웹 UI 제공
- 리서치 실행 전 데이터 완전성을 점검하는 mart coverage audit 도구 제공

## 아키텍처

```text
외부 API
  SEC / Alpha Vantage / yfinance / Tiingo / FRED
        |
        v
Python 수집 CLI 및 Airflow DAG
        |
        v
PostgreSQL raw/meta 테이블 + MinIO 객체 저장소
        |
        v
dbt staging 및 intermediate 모델
        |
        v
전략 mart, coverage audit, 백테스트 웹 UI
```

핵심 구성 요소:

- Python 패키지: `quant_data_platform`
- CLI 엔트리포인트: `quant-pipeline`
- 오케스트레이션: `dags/` 아래 Airflow DAG
- 변환 계층: `dbt/` 아래 dbt 프로젝트
- 웹 앱: `quant_data_platform.web.app`
- 로컬 인프라: `docker-compose.yml`

## 데이터 소스

- `Alpha Vantage`: 상장 상태와 심볼 overview 데이터
- `yfinance`: 장기 가격 백필, 배당, 분할, 기업행위 참고 데이터
- `Tiingo`: 일별 증분 가격 업데이트
- `SEC`: EDGAR submissions와 company facts
- `FRED`: 매크로 및 무위험 금리 시계열
- `Alpaca`: 선택 사항인 paper trading 대시보드 연동

## 요구 사항

- Docker 및 Docker Compose
- Python 3.12 이상
- `uv`
- 사용할 live data source의 API credential

예시 환경 파일을 복사하고 로컬 값을 채웁니다.

```bash
cp .env.example .env
```

주요 환경 변수:

- `ALPHAVANTAGE_API_KEY`
- `TIINGO_API_KEY`
- `FRED_API_KEY`
- `SEC_USER_AGENT`, 예: `Your Name your@email.com`
- `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, Alpaca paper trading 사용 시 필요
- `INFRA_HOST`, 기본값 `localhost`
- `POSTGRES_PORT`, 기본값 `55432`

`.env` 파일이나 실제 credential은 커밋하지 마세요.

## 빠른 시작

로컬 인프라를 초기화합니다.

```bash
docker compose up --build airflow-init
docker compose up -d postgres minio pgadmin airflow-webserver airflow-scheduler
```

기본 `INFRA_HOST=localhost` 기준 서비스 엔드포인트:

- Airflow: <http://localhost:8080>
- MinIO API: <http://localhost:9000>
- MinIO Console: <http://localhost:9001>
- pgAdmin: <http://localhost:5050>
- PostgreSQL: `localhost:55432`

pgAdmin 로그인 값은 아래 환경 변수를 사용합니다.

- `PGADMIN_DEFAULT_EMAIL`
- `PGADMIN_DEFAULT_PASSWORD`

PostgreSQL 서버는 pgAdmin에 `quant-postgres` 이름으로 등록됩니다.

## 주요 CLI 명령

```bash
uv sync
uv run quant-pipeline build-universe
uv run quant-pipeline backfill-market --mode recent
uv run quant-pipeline backfill-fundamentals --mode full
uv run quant-pipeline sync-fred --series DGS3MO DGS10
uv run quant-pipeline daily-incremental
uv run quant-pipeline audit-mart-coverage --cohort us_liquidity_700_v1
```

JSON audit 출력:

```bash
uv run quant-pipeline audit-mart-coverage --cohort us_liquidity_700_v1 --format json
```

## Airflow DAG

- `backfill_market_data`
- `backfill_fundamentals`
- `daily_incremental_pipeline`
- `build_liquidity_universe`

full-universe refresh 예시:

```bash
docker compose exec airflow-webserver airflow dags trigger backfill_fundamentals --conf '{"full_universe": true, "mode": "full"}'
docker compose exec airflow-webserver airflow dags trigger backfill_market_data --conf '{"full_universe": true, "mode": "recent"}'
docker compose exec airflow-webserver airflow dags trigger build_liquidity_universe
docker compose exec airflow-webserver airflow dags trigger daily_incremental_pipeline
```

CLI로 실행할 수도 있습니다.

```bash
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run quant-pipeline backfill-fundamentals --full-universe --mode full
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run quant-pipeline backfill-market --full-universe --mode recent
```

## dbt 모델

- `stg_*`: 원천 데이터 정규화
- `int_*`: point-in-time fundamentals, total-return prices, universe snapshots
- `mart_*`: 전략별 백테스트 입력 mart

현재 mart 계열:

- `mart_value_quality_inputs`
- `mart_value_momentum_inputs`
- `mart_quality_lowvol_inputs`

`stg_daily_prices`는 Tiingo와 yfinance 데이터가 같은 날짜에 겹치면 Tiingo row를 우선합니다.

## 백테스트와 웹 UI

권장 웹 실행 경로는 Docker입니다.

```bash
docker compose up -d postgres backtest-web
```

기본 route:

- Backtest UI: `http://${INFRA_HOST}:8000/backtest`
- Current bucket: `http://${INFRA_HOST}:8000/current_bucket`
- Alpaca paper trading: `http://${INFRA_HOST}:8000/alpaca`
- Health check: `http://${INFRA_HOST}:8000/healthz`

로컬 FastAPI 실행:

```bash
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run uvicorn quant_data_platform.web.app:app --reload
```

원격 인프라를 바라보려면 `INFRA_HOST`와 필요한 경우 `POSTGRES_PORT`를 변경합니다.

## 마켓 타이밍

백테스트 엔진에는 `references/mkt_timing_strategy.md`에 정리된 비대칭 이동평균과 canary asset signal 기반 마켓 타이밍 아이디어가 포함되어 있습니다. 시장 하락기 방어 효과를 시뮬레이션할 때 사용할 수 있습니다.

## 테스트

로컬 테스트:

```bash
uv run pytest
```

credential 설정 후 live integration 테스트:

```bash
ALPHAVANTAGE_API_KEY=... \
TIINGO_API_KEY=... \
FRED_API_KEY=... \
SEC_USER_AGENT="Your Name your@email.com" \
uv run pytest -m integration
```

Docker Compose 설정 검증:

```bash
docker compose config
```

## 관련 문서

- [Agent Core](docs/agent-core.md)
- [Repository Guide](REPO_GUIDE.md)
- [Quant Strategy Documentation](research_report/quant_strategy_documentation_en.md)
- [Backtest Data Requirements](research_report/us_equity_backtest_data_requirements_en.md)
- [Quant Factor Research](research_report/us_equity_quant_factor_research_en.md)

## 공개 저장소 주의 사항

- `.env`, 로컬 데이터 볼륨, 백업, 캐시, 생성된 dbt/Airflow 상태 파일은 ignore 대상입니다.
- API key, broker credential, 개인 계정 식별자, 로컬 DB dump는 커밋하지 마세요.
- 백테스트 결과는 리서치 근거일 뿐 미래 성과를 보장하지 않습니다.
