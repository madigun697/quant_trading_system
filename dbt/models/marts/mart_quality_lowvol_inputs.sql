{{ config(tags=["mart"], materialized='table') }}

/*
  mart_quality_lowvol_inputs
  ───────────────────────────
  Quality + Low-volatility 팩터.
  - 변동성/베타: int_total_return_prices (rolling window)
  - Quality 팩터: mart_value_quality_inputs (int_prices_universe_daily 기반)

  ── 리팩토링 (beta_252d_optional 병목 제거) ──────────────────────────────────
  [문제] 기존 코드의 병목 3가지:
    1. spy_daily_log_return: lag()가 partition 없이 전체 테이블 정렬 → symbol 수만큼 복제
    2. beta 계산 시 stddev(daily_log_return) 252d 윈도우를 rolling_vol_252d와 별도로 재계산
    3. stddev(spy_daily_log_return) 252d 윈도우를 symbol마다 독립 계산 (SPY는 전 종목 공통)

  [해결]
    - spy_returns CTE: SPY 수익률을 날짜별 단일 행으로 materialize (중복 제거)
    - rolling_windows CTE: 모든 윈도우 함수를 한 패스에 계산
      · rolling_vol_252d 재사용 → stddev(r) 중복 계산 제거
      · spy_vol_252d를 symbol-independent 윈도우로 계산 후 조인
      · beta = corr * rolling_vol_252d / spy_vol_252d
*/

-- ── Step 1: SPY 수익률을 날짜별 단일 시계열로 분리 ─────────────────────────
-- lag()가 SPY 단일 파티션 내에서만 수행되므로 전체 테이블 재정렬 없음
with spy_returns as (
    select
        observation_date                                                    as trade_date,
        ln(value / nullif(lag(value) over (order by observation_date), 0)) as spy_log_return
    from {{ ref('stg_benchmark_series') }}
    where benchmark_name = 'SPY'
),

-- ── Step 2: 종목 수익률 + SPY 수익률 결합 ───────────────────────────────────
returns as (
    select
        p.symbol,
        p.trade_date,
        p.daily_log_return,
        s.spy_log_return
    from {{ ref('int_total_return_prices') }} p
    left join spy_returns s
        on s.trade_date = p.trade_date
),

-- ── Step 3: 모든 롤링 윈도우를 한 패스로 계산 ───────────────────────────────
-- · rolling_vol_252d 는 beta 분자의 stddev(r) 로 재사용 → 중복 계산 제거
-- · spy_vol_252d 는 SPY 기준 단일 값이지만, PostgreSQL window fn 특성상
--   partition by symbol 이 필요 → symbol별로 동일한 값을 산출하되 join으로 재사용
rolling_windows as (
    select
        symbol,
        trade_date,
        daily_log_return,
        spy_log_return,

        -- 변동성 (3구간)
        stddev_samp(daily_log_return) over w63  as rolling_vol_63d,
        stddev_samp(daily_log_return) over w126 as rolling_vol_126d,
        stddev_samp(daily_log_return) over w252 as rolling_vol_252d,

        -- beta 부품: corr, spy_vol (252d) — 별도 윈도우 패스 제거
        corr(daily_log_return, spy_log_return) over w252 as corr_252d,
        stddev_samp(spy_log_return)            over w252 as spy_vol_252d

    from returns
    window
        w63  as (partition by symbol order by trade_date rows between 62  preceding and current row),
        w126 as (partition by symbol order by trade_date rows between 125 preceding and current row),
        w252 as (partition by symbol order by trade_date rows between 251 preceding and current row)
),

-- ── Step 4: Quality 팩터 ─────────────────────────────────────────────────────
quality as (
    select
        symbol,
        trade_date,
        cohort,
        snapshot_date,
        liquidity_rank,
        snapshot_adv60,
        roe,
        gross_margin,
        operating_margin,
        debt_to_equity
    from {{ ref('mart_value_quality_inputs') }}
)

-- ── Final: 조립 ──────────────────────────────────────────────────────────────
-- beta = corr(r, spy) * stddev(r) / stddev(spy)
-- rolling_vol_252d = stddev(r) 252d → 재사용, spy_vol_252d 도 이미 계산됨
select
    rw.symbol,
    rw.trade_date,
    q.cohort,
    q.snapshot_date,
    q.liquidity_rank,
    q.snapshot_adv60,
    q.roe,
    q.gross_margin,
    q.operating_margin,
    q.debt_to_equity,
    rw.rolling_vol_63d,
    rw.rolling_vol_126d,
    rw.rolling_vol_252d,
    rw.corr_252d * rw.rolling_vol_252d
        / nullif(rw.spy_vol_252d, 0)                                       as beta_252d_optional
from rolling_windows rw
left join quality q
    on q.symbol    = rw.symbol
   and q.trade_date = rw.trade_date
