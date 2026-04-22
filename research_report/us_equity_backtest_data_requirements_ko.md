# 미국 주식 3개 전략 백테스트용 데이터 요구사항 보고서

## 1. 목적과 범위
이 문서는 미국 주식 시장을 대상으로 하는 아래 3개 전략의 백테스트를 위해 필요한 데이터 요구사항을 정리한 엔지니어링용 설계 문서다.

- `Value + Quality`
- `Value + Momentum`
- `Quality + Low Volatility`

초점은 전략 아이디어 자체의 설명이 아니라, 엔지니어가 이후 데이터 수집 파이프라인을 코드로 구현할 수 있도록 어떤 원시 데이터가 필요하고, 어떤 방식으로 수집하며, 어떤 원시 데이터가 어떤 팩터 계산으로 이어지는지를 명확히 정리하는 데 있다.

기본 전제는 다음과 같다.

- 대상 유니버스는 NYSE, Nasdaq, AMEX 상장 보통주다.
- ETF, ADR, 우선주, 극저유동성 종목은 제외한다.
- 리밸런싱은 월 1회 기준이다.
- 백테스트는 point-in-time 데이터 접근을 전제로 한다.
- filing lag, delisting, symbol change, corporate action 처리가 필수다.

## 2. 전략별 데이터 요구 개요
세 전략은 공통적으로 다음 데이터 계층을 공유한다.

- 종목 마스터와 식별자 매핑
- 상장/상장폐지 및 심볼 변경 이력
- 일별 가격, 거래량, 배당, 분할 등 기업행동
- 재무제표 원시 데이터와 공시 메타데이터
- 섹터/산업 분류
- 거래 캘린더
- 벤치마크 수익률과 무위험수익률

전략별 차이는 아래와 같다.

- `Value + Quality`
  - 재무제표 활용도가 가장 높다.
  - 가치와 수익성, 재무건전성, 이익품질 지표 계산이 핵심이다.
- `Value + Momentum`
  - 가치 계산용 재무 데이터에 더해, 일별 조정주가 기반 total return 시계열이 필수다.
  - 12-1 모멘텀처럼 최근 1개월 제외 규칙을 반영할 수 있어야 한다.
- `Quality + Low Volatility`
  - 품질 계산용 재무 데이터와 함께 일별 수익률 기반 realized volatility가 필수다.
  - `beta`는 기본값이 아니라 선택 확장 데이터로 취급한다.

## 3. 공통 데이터 계층
### 3.1 보안/종목 마스터
필수 필드는 아래와 같다.

- `ticker`
- `CIK`
- `exchange`
- `security_type`
- `primary_listing_flag`
- `active_delisted_status`
- `listing_date`
- `delisting_date`
- `symbol_change_history`
- 가능하면 `CUSIP`, `ISIN`, `FIGI` 등 추가 식별자

필요 이유는 아래와 같다.

- 가격, 공시, 재무제표, 기업행동 데이터를 안정적으로 조인하기 위해 필요하다.
- `ticker`는 시계열 중간에 바뀔 수 있으므로 지속 식별자 관리가 필요하다.
- 상장폐지 종목을 유니버스에서 제거하면 survivorship bias가 발생한다.

수집 시 주의점은 아래와 같다.

- 종목 식별의 중심축은 `ticker`가 아니라 `CIK` 또는 내부 `stable_id`여야 한다.
- 심볼 변경 이력은 현재값 덮어쓰기가 아니라 이벤트 로그 형태로 보존해야 한다.
- 상장 상태는 스냅샷과 이벤트 로그를 함께 보관하는 것이 좋다.

### 3.2 상장/상장폐지 이력
필수 필드는 아래와 같다.

- `symbol`
- `status`
- `listing_date`
- `delisting_date`
- `delisting_reason` 가능 시
- `status_effective_date`

필요 이유는 아래와 같다.

- 과거 시점 유니버스를 복원하려면 당시 상장 중이던 종목만 정확히 포함해야 한다.
- 상장폐지 종목의 마지막 거래일과 상태 전환 시점을 알아야 백테스트 종료 가격 처리와 survivorship bias 방지가 가능하다.

수집 시 주의점은 아래와 같다.

- 공급자마다 delisting coverage가 다르므로 교차 검증이 필요하다.
- delisting_date와 마지막 거래일은 반드시 같은 값이 아닐 수 있다.

### 3.3 일별 가격/거래량/기업행위
필수 필드는 아래와 같다.

- `trade_date`
- `open`, `high`, `low`, `close`
- `adjusted_close` 또는 `adjustment_factor`
- `volume`
- `dividend_amount`
- `split_factor`
- `corporate_action_type`

필요 이유는 아래와 같다.

- 모멘텀, realized volatility, beta, 수익률, 거래대금, 리밸런싱 체결 가격 계산에 필요하다.
- 배당과 분할이 누락되면 total return 기반 신호가 왜곡된다.
- raw price와 adjusted price를 둘 다 보유해야 corporate action 처리 검증이 가능하다.

수집 시 주의점은 아래와 같다.

- 조정주가 계산 방식은 벤더별로 다를 수 있으므로 내부 기준을 고정해야 한다.
- 월말 신호를 쓴다면 월말 종가 시점과 익영업일 시가 체결 규칙을 일관되게 유지해야 한다.
- 거래정지, 이상치, 분할 전후 불연속은 별도 품질 검사 대상이다.

### 3.4 재무제표 및 공시 메타데이터
필수 필드는 아래와 같다.

- Income statement
  - `revenue`
  - `gross_profit`
  - `operating_income`
  - `EBITDA`
  - `interest_expense`
  - `net_income`
  - `basic_eps`
  - `diluted_eps`
  - `weighted_average_shares`
- Balance sheet
  - `total_assets`
  - `total_liabilities`
  - `total_equity`
  - `cash_and_equivalents`
  - `short_term_debt`
  - `long_term_debt`
- Cash flow statement
  - `operating_cash_flow`
  - `capex`
  - `dividends_paid`
  - `share_repurchases` 가능 시
- Filing metadata
  - `period_end`
  - `fiscal_year`
  - `fiscal_quarter`
  - `filing_date`
  - `accepted_datetime` 또는 `effective_as_of`
  - `accession_number`
  - `restatement_flag`

필요 이유는 아래와 같다.

- 가치, 수익성, 재무건전성, 이익품질, 현금창출력 지표 계산의 기초다.
- point-in-time 백테스트를 위해서는 수치 자체보다도 “언제 시장이 이 정보를 알 수 있었는지”가 중요하다.

수집 시 주의점은 아래와 같다.

- `period_end` 기준이 아니라 `filing_date` 또는 실제 접근 가능 시점 기준으로 사용 가능 여부를 판단해야 한다.
- 수정 공시(restatement)는 원본을 덮어쓰지 말고 버전별로 구분해 저장해야 한다.
- XBRL 원천 데이터는 항목명 표준화와 기업별 taxonomy extension 처리 작업이 필요할 수 있다.

### 3.5 섹터/산업 분류
필수 필드는 아래와 같다.

- `sector`
- `industry`
- `sic` 또는 `gics_like_classification`
- `classification_effective_date`

필요 이유는 아래와 같다.

- Value와 Quality 지표는 산업별 분포 차이가 커서 normalization이나 sector-neutral 비교에 필요하다.
- Quality + Low Volatility는 특정 방어 섹터 편중 여부를 감시해야 한다.

수집 시 주의점은 아래와 같다.

- 분류 체계는 공급자별로 다를 수 있으므로 내부 표준 분류로 매핑하는 것이 좋다.
- 시계열 중 업종 분류가 바뀌는 경우 effective date를 보존해야 한다.

### 3.6 거래 캘린더
필수 필드는 아래와 같다.

- `trade_date`
- `is_open`
- `session_type`
- `market_open_time`
- `market_close_time`

필요 이유는 아래와 같다.

- 월말 리밸런싱, filing lag 적용, 다음 영업일 시가 체결 규칙 구현에 필요하다.

### 3.7 벤치마크/무위험수익률
필수 필드는 아래와 같다.

- `benchmark_price` 또는 `benchmark_return`
- `risk_free_rate`
- beta를 쓸 경우 `market_return_series`

필요 이유는 아래와 같다.

- 초과수익률, Sharpe, beta 계산을 위해 필요하다.
- `Quality + Low Volatility`의 beta 확장 버전에서 벤치마크 수익률이 요구된다.

수집 시 주의점은 아래와 같다.

- 무위험수익률은 일별 또는 전략 보유기간에 맞춰 정렬해야 한다.
- 벤치마크 수익률과 개별 종목 수익률의 캘린더를 맞춰야 한다.
- `beta` 확장 버전의 기본 벤치마크는 일별 `SPY` 조정주가 기반 total return 시계열로 고정하고, 종목 가격과 같은 공급자 계열에서 수집하는 것을 우선 규칙으로 둔다.

## 4. 전략별 상세 데이터 목록
### 4.1 Value + Quality
#### 필수 원시 필드
- 가격/시가총액 관련
  - `close`
  - `adjusted_close`
  - `shares_outstanding` 또는 시가총액 계산 가능 필드
- 재무제표 관련
  - `net_income`
  - `total_equity`
  - `total_assets`
  - `gross_profit`
  - `operating_income`
  - `EBITDA`
  - `revenue`
  - `cash_and_equivalents`
  - `short_term_debt`
  - `long_term_debt`
  - `operating_cash_flow`
  - `capex`
  - `interest_expense`
  - working capital 관련 항목 또는 accruals 계산 가능 필드
- 메타데이터
  - `period_end`
  - `filing_date`
  - `effective_as_of`

#### 필드가 필요한 이유
- Value 계산에는 주가, 시가총액, EV 계산용 부채/현금, 수익 또는 현금흐름 계정이 필요하다.
- Quality 계산에는 수익성, 마진, 레버리지, 이익품질, 이자보상능력 관련 계정이 필요하다.

#### 파생 가능한 팩터
- Value
  - `P/E`
  - `P/B`
  - `EV/EBITDA`
  - `FCF Yield`
  - `Sales Yield`
- Quality
  - `ROE`
  - `ROIC`
  - `Gross Margin`
  - `Operating Margin`
  - `Debt-to-Equity`
  - `Interest Coverage`
  - `Accruals`

#### Point-in-Time Notes
- EV 계산에 쓰이는 시가총액은 공시 시점과 가까운 market data 기준이어야 한다.
- `weighted_average_shares`와 `shares_outstanding`은 정의가 다를 수 있으므로 내부 기준을 고정해야 한다.
- 산업별 분포 차이가 큰 지표는 sector-neutral rank 또는 winsorization 검토가 필요하다.

### 4.2 Value + Momentum
#### 필수 원시 필드
- Value 파트
  - `Value + Quality`의 가치 계산 최소 집합
- Momentum 파트
  - 최소 13개월 이상 또는 `252거래일 + skip-month`를 충족하는 일별 `adjusted_close`
  - 배당/분할 반영 정보
  - 거래 캘린더

#### 필드가 필요한 이유
- Value는 가격 대비 내재 펀더멘털 저평가를 찾기 위해 필요하다.
- Momentum은 가격 추세와 total return 성과를 측정하기 위해 필요하다.

#### 파생 가능한 팩터
- `12M total return`
- `6M total return`
- `3M total return`
- `12-1 momentum`
- `relative strength`

#### Point-in-Time Notes
- 모멘텀은 반드시 adjusted price 또는 total return 기준으로 계산한다.
- 최근 1개월 제외 규칙은 거래일 창으로 명확히 정의해야 하며, `12-1 momentum` 구현을 위해 최소 13개월 수준의 히스토리를 확보해야 한다.
- 분할/배당 반영 누락은 모멘텀 왜곡을 일으키므로 corporate action 검증이 중요하다.

### 4.3 Quality + Low Volatility
#### 필수 원시 필드
- Quality 파트
  - `Value + Quality`의 품질 계산 핵심 집합
- Low Volatility 파트
  - 최소 12개월 일별 `adjusted_close`
  - 일별 수익률 계산용 거래 캘린더
- Beta 확장 파트
  - `benchmark_return_series`
  - 회귀 창 정의용 메타데이터

#### 필드가 필요한 이유
- Quality는 재무 안정성과 수익성의 질을 측정한다.
- Low Volatility는 realized volatility 기반으로 안정적 가격 움직임을 측정한다.
- Beta는 선택적으로 시장 민감도를 측정하기 위한 확장 지표다.

#### 파생 가능한 팩터
- Quality
  - `ROE`
  - `ROA`
  - `Gross Margin`
  - `Operating Margin`
  - `Debt-to-Equity`
- Low Volatility
  - `63d rolling volatility`
  - `126d rolling volatility`
  - `252d rolling volatility`
- Optional
  - `beta`

#### Point-in-Time Notes
- 기본 저변동성 정의는 `rolling daily return volatility`로 고정한다.
- `beta`는 대체 구현 또는 보조 필터이며 기본 요구사항이 아니다.
- `beta`를 사용할 경우 기본 벤치마크는 일별 `SPY` 조정주가 기반 total return 시계열로 고정하고, 종목 수익률과 같은 거래일 기준으로 정렬해야 한다.

## 5. 데이터 원천 및 수집 방법 매트릭스
| 데이터 범주 | 필수 필드 | 무료 원천 | 무료 수집 방법 | 유료 원천 | 유료 수집 방법 | 선정 이유 | 주의점 |
|---|---|---|---|---|---|---|---|
| 종목 마스터 / 상장 상태 / 심볼 매핑 | ticker, CIK, exchange, status, listing date, delisting date, symbol history | SEC EDGAR submissions, Alpha Vantage LISTING_STATUS | CIK 기반 마스터 구축, 일별 또는 주별 증분 수집, 정기 full refresh | EODHD fundamentals/delisted/reference, Polygon reference | 일별 증분 + 주기적 전체 재조정 | 무료는 공식성과 접근성, 유료는 delisting과 symbol change coverage가 강함 | 공급자별 식별자 체계 차이, delisting date와 마지막 거래일 불일치 가능 |
| 일별 가격 / 거래량 / 배당 / 분할 | OHLCV, adjusted close, dividend, split factor | Alpha Vantage TIME_SERIES_DAILY_ADJUSTED | 종목별 API 순회, 누락분 재시도, 일별 증분 수집 | Polygon Stocks REST/Flat Files | Flat file 초기 백필 후 REST 일별 증분 | 무료는 빠른 프로토타입 적합, 유료는 품질과 확장성이 우수 | Alpha Vantage 속도 제한, 공급자별 조정주가 계산 차이 |
| 재무제표 원시 데이터 | revenue, gross profit, operating income, EBITDA, net income, assets, liabilities, equity, cash, debt, OCF, capex | SEC EDGAR companyfacts, SEC bulk ZIP | filing event 기반 증분, accession number 단위 버전 저장 | Polygon financial statement endpoints, EODHD fundamentals | 분기 공시 이후 증분 수집 + 스냅샷 저장 | 무료는 원천 공시 기반, 유료는 정규화가 쉬워 엔지니어링 비용이 낮음 | XBRL 매핑 필요, 벤더별 항목 정의와 restatement 처리 차이 |
| 공시 메타데이터 | period_end, filing_date, accepted_datetime, accession_number, restatement_flag | SEC EDGAR submissions | filing feed 기반 이벤트 수집 | Polygon financial statement metadata, EODHD fundamentals metadata | 분기 증분 수집 | point-in-time 처리의 핵심 메타데이터는 공시 원천 기반이 가장 중요 | accepted time 누락 시 availability 추정 규칙 필요 |
| 섹터/산업 분류 | sector, industry, sic/gics-like code, effective date | Alpha Vantage OVERVIEW, SEC SIC metadata 일부 활용 | 주기적 스냅샷 수집 | Polygon ticker overview/reference, EODHD fundamentals | 주별 또는 월별 증분 수집 | 전략 normalization과 sector exposure 점검에 필요 | 분류체계 차이, 시계열 중 분류 변경 발생 가능 |
| 거래 캘린더 | trade_date, market_open, market_close, session status | 가격 소스 기준 거래일 캘린더, 필요 시 거래소 공식 캘린더 보조 | 가격 데이터에서 open day 추출 + 휴장일 검증 | Polygon market status/calendar 계열 데이터 | 일별 증분 | 백테스트 체결 시점과 filing lag 정렬에 필수 | 반일장, 휴장일, 비정상 세션 처리 필요 |
| 벤치마크 / 무위험수익률 | benchmark return, risk-free rate, optional market return series | FRED API + Alpha Vantage SPY adjusted series | 무위험수익률은 FRED series ID 기준 증분 수집, beta용 벤치마크는 SPY 일별 조정주가 시계열 수집 | Nasdaq Data Link premium 또는 Polygon SPY series | 일정 주기 증분 수집 | 무위험수익률은 FRED가 적합하고, beta용 시장 프록시는 종목 가격과 같은 계열의 일별 SPY total return 프록시가 재현성이 높음 | FRED 단독으로는 beta 계산용 시장수익률 대체가 부정확할 수 있고, SPY 사용 시 ETF 프록시라는 점을 문서화해야 함 |
| 상장폐지 / 참조 보강 | delisting status, delisting date, corporate reference history | SEC submissions, Alpha Vantage LISTING_STATUS | 이벤트 기반 증분 수집 | EODHD delisted/reference, Polygon reference | 일별 스냅샷 + 이벤트 로그 저장 | survivorship bias 방지에 핵심 | 무료 소스만으로는 delisting coverage가 약할 수 있음 |

## 6. 권장 원천 조합
### 6.1 무료 우선 스택
- `SEC EDGAR submissions/companyfacts/bulk ZIP`
- `Alpha Vantage TIME_SERIES_DAILY_ADJUSTED`
- `Alpha Vantage OVERVIEW`
- `Alpha Vantage LISTING_STATUS`
- `FRED API`

적합한 경우는 아래와 같다.

- 프로토타입 백테스트
- 종목 수가 제한된 리서치
- 비용을 최소화해야 하는 초기 검증

장점은 아래와 같다.

- 원천 공시와 공개 API 기반이라 진입장벽이 낮다.
- PoC를 빠르게 만들기 좋다.

한계는 아래와 같다.

- 심볼 변경과 상장폐지 커버리지가 약할 수 있다.
- XBRL 정규화와 데이터 정합성 검증 부담이 크다.
- 대규모 유니버스 운영에는 수집 속도와 안정성이 부족할 수 있다.

### 6.2 유료 우선 스택
- `Polygon Stocks REST/Flat Files`
- `Polygon financial statement endpoints`
- `EODHD fundamentals/delisted/reference`
- `FRED API`
- `SEC EDGAR`는 원천 검증용 보조 저장

적합한 경우는 아래와 같다.

- 대규모 유니버스 백테스트
- 반복 리서치 운영
- delisted 포함 장기 히스토리 복원

장점은 아래와 같다.

- 가격/기업행동 데이터 품질이 높다.
- reference와 delisting coverage가 더 좋다.
- 증분 수집과 백필 운영이 상대적으로 단순하다.

한계는 아래와 같다.

- 비용과 라이선스 관리가 필요하다.
- 벤더별 정의 차이를 내부 표준으로 정규화해야 한다.

### 6.3 현실적 하이브리드 권장안
- 재무/공시 원천: `SEC`
- 가격/기업행동: `Polygon`
- delisting/reference 보강: `EODHD`
- 무위험수익률/보조 거시 데이터: `FRED`
- 기관용 보조 대안: `Nasdaq Data Link premium`

권장 이유는 아래와 같다.

- 원천 공시와 정규화된 상업용 데이터의 장점을 동시에 활용할 수 있다.
- 데이터 레이어별 책임 분리가 명확하다.
- 운영 난이도, 품질, 비용의 균형이 가장 좋다.

## 7. 엔지니어 핸드오프 메모
권장 canonical entity는 아래와 같다.

- `security_master`
- `daily_prices`
- `corporate_actions`
- `fundamentals_income_statement`
- `fundamentals_balance_sheet`
- `fundamentals_cash_flow`
- `filing_metadata`
- `benchmark_series`

각 엔티티에는 최소한 아래 메타데이터를 포함하는 것이 좋다.

- `symbol`
- `stable_id` 또는 `CIK`
- `trade_date` 또는 `period_end`
- `filing_date`
- `effective_as_of`
- `source`

수집 및 저장 원칙은 아래와 같다.

- raw layer와 normalized layer를 분리한다.
- raw ingestion record에는 `source_id`, `ingested_at`, `available_at`을 보관한다.
- point-in-time 조회는 `available_at` 이전 데이터만 허용한다.
- filing lag는 단순 `period_end`가 아니라 시장 접근 가능 시점 기준으로 적용한다.
- 월말 리밸런싱이면 해당 월말 시점 이전에 접근 가능한 데이터만 사용한다.

권장 수집 패턴은 아래와 같다.

- 가격/기업행동
  - 초기 백필: bulk 또는 장기 히스토리 다운로드
  - 이후 운영: 일별 증분
- 공시/재무제표
  - filing event 기반 증분 수집
  - 정기적 전체 재검증
- 종목 마스터/상장 상태
  - 일별 또는 주별 증분
  - 주기적 full refresh

최소 품질 점검 항목은 아래와 같다.

- 누락 심볼
- 중복 공시
- 분할 전후 가격 불연속
- 재무제표 합계 불일치
- delisted 종목의 마지막 거래일 오류
- 심볼 변경 후 잘못된 조인

## 8. 리스크와 구현 시 주의사항
- `survivorship bias`
  - 상장폐지 종목이 빠지면 과거 성과가 과대평가된다.
- `look-ahead bias`
  - filing lag를 무시하고 공시 전 데이터를 사용하면 신호가 왜곡된다.
- `ticker drift`
  - 심볼 변경과 재상장을 제대로 추적하지 못하면 가격/재무 조인이 틀어진다.
- `restatement bias`
  - 수정 공시를 과거 시점에 소급 반영하면 실제보다 좋은 성과가 나온다.
- `split/dividend drift`
  - 조정주가 계산이 벤더별로 다르면 모멘텀과 변동성 신호가 달라진다.
- `vendor mismatch`
  - 동일 필드라도 벤더마다 정의와 계산 방식이 다를 수 있다.
- `low volatility 오해`
  - 기본값은 realized volatility이며, beta는 선택 확장이다.
- `momentum 훼손`
  - total return이 아니라 unadjusted price로 계산하면 모멘텀 신호가 잘못된다.

## 9. 결론
세 전략의 백테스트를 위한 데이터 파이프라인은 공통적으로 point-in-time 처리, filing lag, stable identifier 관리, delisting/symbol change 대응, incremental sync 구조를 갖춰야 한다. 무료 기반 프로토타입은 `SEC + Alpha Vantage + FRED`로 시작할 수 있지만, 운영 가능성과 품질을 고려하면 `SEC + Polygon + EODHD + FRED` 하이브리드 구성이 가장 실무적이다. `Quality + Low Volatility` 전략에서는 저변동성의 기본 정의를 `rolling daily return volatility`로 두고, `beta`는 선택 확장으로만 다루는 것을 권장한다.
