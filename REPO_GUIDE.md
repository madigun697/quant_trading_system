# Quant Data Platform — 레포지토리 종합 가이드

> 작성일: 2026-04-25  
> 본 문서는 레포지토리의 목적, 구현 구성, 수행 가능한 작업을 정리한 읽기 전용 참조 문서입니다.

---

## 1. 레포지토리 개요

### 1.1 목적

이 레포지토리는 **미국 주식 퀀트/팩터 기반 백테스트 및 Paper Trading 데이터 파이프라인 프로토타입**입니다.

무료 또는 저비용 공개 데이터 소스(SEC, Alpha Vantage, yfinance, Tiingo, FRED)로부터 미국 주식의 가격, 재무제표, 벤치마크, 상장 메타데이터를 수집하고, 이를 PostgreSQL에 적재한 뒤 dbt로 변환하여 **팩터 백테스트에 필요한 입력 마트 테이블**을 생성합니다.
추가적으로 마켓 타이밍 전략(`mkt_timing_strategy.md`) 및 Alpaca API를 연동한 모의투자(Paper Trading) 대시보드 기능까지 통합 지원합니다.

### 1.2 전략 배경

`research_report/` 디렉토리의 리서치 보고서에 따르면, 다음 세 가지 팩터 조합 전략을 우선 백테스트 대상으로 선정하고 있습니다:

| 전략 조합 | 대응 마트 테이블 |
|---|---|
| Value + Quality | `mart_value_quality_inputs` |
| Value + Momentum | `mart_value_momentum_inputs` |
| Quality + Low Volatility | `mart_quality_lowvol_inputs` |

### 1.3 기술 스택 요약

| 영역 | 기술 |
|---|---|
| 언어 | Python 3.12+ |
| 패키지 관리 | uv (pyproject.toml + uv.lock) |
| 런타임 | Docker Compose (6개 서비스) |
| 스토리지 | PostgreSQL 16 (구조화 데이터) + MinIO (원본 JSON 아카이브) |
| 변환 | dbt-postgres (staging → intermediate → marts) |
| 오케스트레이션 | Apache Airflow 2.10.5 (LocalExecutor) |
| DB 관리 UI | pgAdmin 4 |
| 웹 프레임워크 | FastAPI + Jinja2 (백테스트 및 모의투자 대시보드) |
| 테스트 | pytest (단위 + 통합) |

---

## 2. 구현 구성 상세

### 2.1 디렉토리 구조

```
quant/
├── src/quant_data_platform/   # Python 핵심 패키지
│   ├── clients/               # 외부 API 클라이언트 (5개)
│   │   ├── alpha_vantage.py   # 상장 상태, 기업 개요
│   │   ├── tiingo.py          # 일별 가격 (증분 + 배치)
│   │   ├── yfinance.py        # 장기 히스토리 백필
│   │   ├── sec.py             # SEC EDGAR 재무제표
│   │   └── fred.py            # FRED 금리 시계열
│   ├── pipeline.py            # 파이프라인 오케스트레이션 로직 (~815줄)
│   ├── db.py                  # PostgreSQL CRUD 함수 (~874줄)
│   ├── config.py              # pydantic-settings 기반 설정
│   ├── storage.py             # DB/S3 커넥션 팩토리
│   ├── object_store.py        # MinIO 업로드 유틸
│   ├── universe.py            # 종목 필터링 규칙 (보통주 판별)
│   ├── utils.py               # JSON 직렬화, 해시, 날짜 파싱
│   └── cli.py                 # CLI 엔트리포인트 (5개 서브커맨드)
├── dags/                      # Airflow DAG 정의 (5개)
├── dbt/                       # dbt 프로젝트
│   ├── models/
│   │   ├── staging/           # 8개 스테이징 모델
│   │   ├── intermediate/      # 6개 중간 모델
│   │   └── marts/             # 3개 마트 모델
│   ├── macros/                # 스키마 이름 생성, 코호트 매크로
│   ├── tests/                 # dbt 데이터 테스트 (2개)
│   ├── dbt_project.yml
│   └── profiles.yml
├── infra/                     # 인프라 설정
│   ├── airflow/Dockerfile     # Airflow 커스텀 이미지
│   ├── airflow/scripts/       # 커넥션 초기화 스크립트
│   ├── postgres/init/         # DB 스키마 부트스트랩 SQL (2개)
│   └── pgadmin/servers.json   # pgAdmin 자동 서버 등록
├── tests/                     # Python 단위/통합 테스트
├── research_report/           # 팩터 리서치 보고서 (한/영)
├── agents/                    # AI 에이전트 프롬프트 라이브러리 (7개 역할)
├── docker-compose.yml         # 전체 서비스 정의
├── pyproject.toml             # Python 프로젝트 메타
├── run_backtest.py            # CLI 백테스트 실행 스크립트
├── mkt_timing_strategy.md     # 마켓 타이밍 전략 리서치 문서
└── .env.example               # 환경변수 템플릿
```

### 2.2 Docker Compose 서비스 구성

총 6개 서비스가 정의되어 있으며, 실제 파이프라인 실행은 **Docker 컨테이너 내부**에서 이루어집니다.

| 서비스 | 이미지 | 역할 | 포트 |
|---|---|---|---|
| `postgres` | postgres:16 | 주 데이터 저장소 | 5432 |
| `minio` | minio/minio | 원본 JSON 아카이브 (S3 호환) | 9000/9001 |
| `pgadmin` | dpage/pgadmin4:9.8 | DB 관리 웹 UI | 5050 |
| `airflow-init` | 커스텀 빌드 | DB 마이그레이션 + 관리자 계정 생성 | - |
| `airflow-webserver` | 커스텀 빌드 | Airflow 웹 UI | 8080 |
| `airflow-scheduler` | 커스텀 빌드 | DAG 스케줄링 및 태스크 실행 | - |

**Airflow Dockerfile** (`infra/airflow/Dockerfile`):
- 베이스: `apache/airflow:2.10.5-python3.12`
- 추가 패키지: `dbt-postgres`, `boto3`, `psycopg`, `pydantic`, `yfinance`, `requests`, `tenacity` 등
- 프로젝트 소스는 볼륨 마운트(`./:/opt/airflow/project`)로 컨테이너에 노출

### 2.3 데이터베이스 스키마

PostgreSQL에 4개 스키마가 자동 생성됩니다 (`01_bootstrap.sql`):

#### `raw` 스키마 — 원천 데이터 적재

| 테이블 | 소스 | 설명 |
|---|---|---|
| `market_daily_prices` | Tiingo / yfinance | 통합 일별 가격 (source별 구분) |
| `market_corporate_actions` | Tiingo / yfinance | 배당·분할 등 기업행위 |
| `alpha_vantage_listing_status` | Alpha Vantage | 상장/상장폐지 상태 |
| `alpha_vantage_overview` | Alpha Vantage | 기업 개요 (CIK, 섹터, 시총) |
| `sec_submissions` | SEC EDGAR | 기업 제출 요약 |
| `sec_ticker_reference` | SEC EDGAR | 심볼↔CIK 매핑 |
| `sec_filing_metadata` | SEC EDGAR | 공시 메타데이터 |
| `sec_companyfacts_facts` | SEC EDGAR | XBRL 재무 팩트 |
| `fred_series_observations` | FRED | 금리 시계열 (예: 3개월 국채) |
| `ingestion_artifacts` | 전체 | 적재 추적 로그 + MinIO 체크섬 |

#### `meta` 스키마 — 유니버스·설정 관리

| 테이블 | 설명 |
|---|---|
| `universe_members` | 코호트별 활성 유니버스 심볼 |
| `universe_rank_snapshots` | 월별 유동성 랭킹 스냅샷 |
| `universe_build_runs` | 유니버스 빌드 실행 이력 |
| `fred_series_config` | 활성 FRED 시리즈 목록 |
| `ingestion_watermarks` | 청크 기반 적재 커서 |

#### `stg` 스키마 — dbt staging + intermediate 결과

#### `mart` 스키마 — dbt 마트 결과

### 2.4 dbt 모델 계층

```
raw (PostgreSQL 원천 테이블)
  └─ staging (view) ─ 정규화·중복 제거·소스 우선순위
       ├── stg_daily_prices          Tiingo 우선, yfinance 보조
       ├── stg_security_master       AV overview + listing + SEC ref 통합
       ├── stg_benchmark_series      SPY(Tiingo) + FRED 시계열 통합
       ├── stg_filing_metadata       SEC 공시 메타
       ├── stg_fundamentals_income_statement   손익계산서
       ├── stg_fundamentals_balance_sheet      대차대조표
       ├── stg_fundamentals_cash_flow          현금흐름표
       └── stg_listing_status_history          상장 상태 이력

       └─ intermediate (table) ─ 무거운 조인·윈도우 사전 계산
            ├── int_total_return_prices       로그 수익률 계산
            ├── int_point_in_time_fundamentals  IS+BS+CF 조인 (PIT 보장)
            ├── int_prices_universe_daily     prices × security × universe × fundamentals
            │                                (가장 핵심적인 중간 테이블, ~230줄)
            ├── int_universe_rank_snapshots   meta에서 선별된 랭킹
            ├── int_universe_snapshots        lead() 기반 유효기간 계산
            └── int_liquidity_scores_monthly  월별 유동성 점수

            └─ marts (table) ─ 팩터별 백테스트 입력
                 ├── mart_value_quality_inputs     PER, PBR, EV/EBITDA, ROE, 마진 등
                 ├── mart_value_momentum_inputs     12-1m, 6m, 3m 모멘텀 + Value
                 └── mart_quality_lowvol_inputs     63/126/252일 변동성, 베타, Quality
```

### 2.5 Airflow DAG 구성

| DAG ID | 스케줄 | 설명 |
|---|---|---|
| `daily_incremental_pipeline` | 평일 19:30 ET | 일별 증분: 소스 수집 → dbt staging → dbt marts → dbt tests |
| `backfill_market_data` | 수동 | 시장 데이터 백필 (yfinance full / Tiingo recent / chunked 모드) |
| `backfill_fundamentals` | 수동 | SEC 재무제표 백필 (full / chunked 모드) |
| `build_liquidity_universe` | 수동 | 유동성 기반 유니버스 구축 (buffer 900 → target 700) |
| `hourly_market_bootstrap` | 수동 | 유니버스 확인 → 청크 백필 → 스냅샷 갱신 (부트스트랩용) |

### 2.6 유니버스 관리 체계

- **Buffer cohort** (`us_liquidity_900_buffer_v1`): ADV60 상위 900개 종목 풀
- **Target cohort** (`us_liquidity_700_v1`): 상위 700개로 축소한 최종 유니버스
- 종목 필터: NYSE/NASDAQ/AMEX 보통주만 허용, ETF·ADR·우선주·워런트 제외
- 유동성 측정: 60일 평균 달러 거래대금(ADV60) 기준 랭킹
- 월별 스냅샷으로 리밸런싱 시점의 유니버스를 히스토리컬하게 관리

### 2.7 데이터 소스별 역할

| 소스 | 용도 | 비용 | rate-limit 대응 |
|---|---|---|---|
| Alpha Vantage | 상장 상태, 기업 개요(CIK, 섹터) | 무료 키 | 15초 쓰로틀 |
| yfinance | 장기 히스토리 백필 (1960~현재) | 무료 | 배치 100건 |
| Tiingo | 일별 증분 가격 업데이트 | 무료 키 | 시간당 50건, 월 1000건 |
| SEC EDGAR | 재무제표(XBRL), 공시 메타 | 무료 | User-Agent 필수 |
| FRED | 무위험 이자율 (3M Treasury) | 무료 키 | - |

### 2.8 Python 패키지 구성

`pyproject.toml` 기준 주요 의존성:
- `psycopg[binary]` ≥ 3.3.3 — PostgreSQL 드라이버
- `boto3` ≥ 1.42.94 — MinIO (S3 호환) 클라이언트
- `pydantic` + `pydantic-settings` — 타입 안전 설정 관리
- `requests` + `tenacity` — HTTP 요청 + 재시도
- `yfinance` ≥ 1.3.0 — Yahoo Finance 가격 데이터
- `python-dotenv` — 환경변수 로딩

CLI 엔트리포인트: `quant-pipeline` (→ `quant_data_platform.cli:main`)

추가적으로 `run_backtest.py` 스크립트를 통해 웹 UI 없이 백테스트 엔진만 단독 실행할 수 있습니다.

---

## 3. 수행 가능한 작업 및 커맨드

### 3.1 환경 구축

#### 최초 설정

```bash
# 1. 환경변수 준비
cp .env.example .env
# .env 파일에 API 키들을 입력

# 2. Airflow 초기화 (DB 마이그레이션 + admin 계정)
docker compose up --build airflow-init

# 3. 서비스 기동
docker compose up -d postgres minio pgadmin airflow-webserver airflow-scheduler
```

#### 접속 정보

| 서비스 | URL | 기본 계정 |
|---|---|---|
| Airflow UI | http://${INFRA_HOST}:8080 | admin / admin |
| MinIO Console | http://${INFRA_HOST}:9001 | minioadmin / minioadmin |
| pgAdmin | http://${INFRA_HOST}:5050 | admin@example.com / admin |
| PostgreSQL | ${INFRA_HOST}:55432 | quant / quant (DB: quant) |

### 3.2 파이프라인 작업 (Airflow UI 또는 CLI)

#### A. 유니버스 구축

**목적**: 유동성 상위 종목을 선별하여 백테스트 유니버스를 생성

```bash
# Airflow UI에서
# DAG: build_liquidity_universe → Trigger

# 또는 Docker 내 CLI
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli build-universe"
```

**수행 내용**: Alpha Vantage 상장 목록 수집 → SEC 티커 참조 수집 → yfinance로 최근 가격 수집 → ADV60 계산 → 버퍼 900 + 타겟 700 유니버스 확정

#### B. 시장 데이터 백필

**목적**: 유니버스 종목의 전체/최근 가격 히스토리를 적재

```bash
# 전체 백필 (yfinance, 1960~현재)
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-market --mode full"

# 청크 백필 (한 번에 100종목씩)
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-market --mode chunked --request-budget 100"

# 최근 데이터만 (Tiingo)
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-market --mode recent"

# 특정 종목만
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-market --symbols AAPL MSFT GOOGL"

# Airflow UI에서: DAG: backfill_market_data → Trigger with config
# 또는: DAG: hourly_market_bootstrap (반복 실행으로 청크 백필)
```

#### C. 재무제표 백필

**목적**: SEC EDGAR에서 XBRL 재무 데이터를 수집

```bash
# 전체 백필
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-fundamentals --mode full"

# 청크 백필 (한 번에 25 CIK씩)
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-fundamentals --mode chunked --request-budget 25"

# 특정 CIK만
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli backfill-fundamentals --ciks 0000320193 0000789019"

# Airflow UI에서: DAG: backfill_fundamentals → Trigger with config
```

#### D. FRED 시계열 동기화

**목적**: 무위험 이자율 등 벤치마크 시계열 갱신

```bash
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli sync-fred --series DGS3MO"
```

#### E. 일별 증분 파이프라인

**목적**: 매일 최신 데이터를 수집하고 dbt 모델을 갱신

```bash
# 수동 실행
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && python -m quant_data_platform.cli daily-incremental"

# 자동: DAG daily_incremental_pipeline이 평일 19:30 ET에 자동 실행
# 실행 흐름: listing 갱신 → 소스 수집 → dbt staging/int → dbt marts → dbt tests
```

#### F. dbt 변환 수동 실행

```bash
# staging + intermediate 모델 실행
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && /home/airflow/.local/bin/dbt run --project-dir dbt --profiles-dir dbt --select tag:stg tag:int"

# mart 모델 실행
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && /home/airflow/.local/bin/dbt run --project-dir dbt --profiles-dir dbt --select tag:mart"

# 특정 모델만
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && /home/airflow/.local/bin/dbt run --project-dir dbt --profiles-dir dbt --select mart_value_quality_inputs"

# dbt 테스트 실행
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && /home/airflow/.local/bin/dbt test --project-dir dbt --profiles-dir dbt"

# dbt 컴파일 (SQL 확인용)
docker compose exec airflow-scheduler bash -lc \
  "cd /opt/airflow/project && /home/airflow/.local/bin/dbt compile --project-dir dbt --profiles-dir dbt"
```

### 3.3 로컬 개발·테스트

```bash
# 단위 테스트 (API 키 불필요, mock 기반)
uv run pytest tests/ -x

# 통합 테스트 (실제 API 호출, 키 필요)
ALPHAVANTAGE_API_KEY=... TIINGO_API_KEY=... FRED_API_KEY=... \
SEC_USER_AGENT="YourName your@email.com" \
uv run pytest tests/ -m integration

# Docker 설정 검증
docker compose config
```

### 3.4 인프라 관리

```bash
# 전체 서비스 중지
docker compose down

# 볼륨 포함 완전 초기화
docker compose down -v

# 특정 서비스 재시작
docker compose restart airflow-scheduler

# 로그 확인
docker compose logs -f airflow-scheduler
docker compose logs -f postgres
```

### 3.5 CLI 전체 커맨드 레퍼런스

| 커맨드 | 설명 | 주요 옵션 |
|---|---|---|
| `build-universe` | 유동성 유니버스 구축 | `--cohort`, `--buffer-size`, `--target-size`, `--discovery-days`, `--lookback-days` |
| `backfill-market` | 시장 데이터 백필 | `--symbols`, `--cohort`, `--mode {full,recent,chunked}`, `--start-date`, `--end-date`, `--request-budget`, `--reset-cursor` |
| `backfill-fundamentals` | 재무제표 백필 | `--ciks`, `--cohort`, `--mode {full,chunked}`, `--as-of-date`, `--request-budget`, `--reset-cursor` |
| `sync-fred` | FRED 시계열 동기화 | `--series` (필수, 복수 가능) |
| `daily-incremental` | 일별 증분 수집 | `--cohort` |

### 3.6 권장 운영 순서 (최초 부트스트랩)

1. `.env` 설정 후 `docker compose up --build airflow-init`
2. `docker compose up -d` 로 전체 서비스 기동
3. Airflow UI에서 `build_liquidity_universe` DAG 트리거 → 유니버스 생성
4. `hourly_market_bootstrap` DAG를 반복 트리거 → 청크 단위 시장 데이터 백필 (remaining_symbols = 0 될 때까지)
5. `backfill_fundamentals` DAG 트리거 (mode=chunked 반복 또는 mode=full 1회)
6. `sync-fred --series DGS3MO` 실행
7. dbt staging → intermediate → marts 순서로 실행
8. `daily_incremental_pipeline` DAG의 schedule 활성화 → 이후 자동 운영

---

## 부록: 환경변수 목록

| 변수 | 기본값 | 설명 |
|---|---|---|
| `POSTGRES_DB` | quant | PostgreSQL DB 이름 |
| `POSTGRES_USER` | quant | DB 사용자 |
| `POSTGRES_PASSWORD` | quant | DB 비밀번호 |
| `MINIO_ROOT_USER` | minioadmin | MinIO 관리자 |
| `MINIO_ROOT_PASSWORD` | minioadmin | MinIO 비밀번호 |
| `ALPHAVANTAGE_API_KEY` | - | Alpha Vantage API 키 |
| `TIINGO_API_KEY` | - | Tiingo API 키 |
| `FRED_API_KEY` | - | FRED API 키 |
| `SEC_USER_AGENT` | - | SEC EDGAR User-Agent |
| `ALPACA_API_KEY` | - | Alpaca API 키 (Paper Trading) |
| `ALPACA_SECRET_KEY` | - | Alpaca Secret 키 |
| `ALPACA_PAPER` | true | Alpaca 모의투자 여부 |
| `DEFAULT_COHORT` | us_liquidity_700_v1 | 기본 타겟 코호트 |
| `UNIVERSE_BUFFER_COHORT` | us_liquidity_900_buffer_v1 | 버퍼 코호트 |
| `UNIVERSE_BUFFER_SIZE` | 900 | 버퍼 유니버스 크기 |
| `UNIVERSE_TARGET_SIZE` | 700 | 타겟 유니버스 크기 |
| `LIQUIDITY_LOOKBACK_DAYS` | 60 | ADV 계산 기간 |
| `LIQUIDITY_DISCOVERY_DAYS` | 90 | 디스커버리 스캔 기간 |
| `TIINGO_HOURLY_REQUEST_BUDGET` | 50 | Tiingo 시간당 요청 한도 |
| `TIINGO_MONTHLY_REQUEST_BUDGET` | 1000 | Tiingo 월간 요청 한도 |
| `YFINANCE_BATCH_SIZE` | 100 | yfinance 배치 크기 |
