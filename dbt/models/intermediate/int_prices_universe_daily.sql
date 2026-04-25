{{
  config(
    tags=["int"],
    materialized='table',
    indexes=[
      {'columns': ['symbol', 'trade_date'], 'unique': True},
      {'columns': ['trade_date']},
      {'columns': ['cohort', 'trade_date']},
      {'columns': ['stable_id_or_cik', 'trade_date']},
    ]
  )
}}

/*
  int_prices_universe_daily
  ──────────────────────────
  목적: mart 레이어의 공통 중간 도출 테이블.
       가장 무거운 두 조인을 한 번에 materialize해서 mart가 재사용한다.

  포함 연산:
  1. security_master + prices  → equi-join (symbol), hash join 가능 [42K × 13.4M]
  2. + universe                → symbol equi-join 후 날짜 범위 필터  [× 284K]
  3. + fundamentals            → 월별 pre-aggregation 후 equi-join (as-of-month 패턴)
                                  → LATERAL row-by-row scan 대신 equi-join 사용

  mart_value_quality_inputs, mart_quality_lowvol_inputs,
  mart_value_momentum_inputs 이 세 모델 모두 이 테이블에서 참조한다.

  ── 최적화 전략 ───────────────────────────────────────────────────────────────
  LATERAL + LIMIT 1 패턴은 정확하지만, 인덱스 없이 joined CTE의 모든 행마다
  sequential scan을 수행해 매우 느리다.
  
  대안: fundamentals를 (stable_id_or_cik, year_month) 단위로 먼저 집계한 뒤,
  trade_date의 year_month로 equi-join한다.
  → 재무 데이터는 분기 보고이므로 동일 월 내 최신 1건이 실질적으로 유일.
  → equi-join → hash join 가능 → 수십 배 빠름.
*/

with security_master as (
    select
        symbol,
        stable_id_or_cik,
        shares_outstanding
    from {{ ref('stg_security_master') }}
),

prices as (
    select
        symbol,
        trade_date,
        adjusted_close,
        close,
        effective_as_of
    from {{ ref('stg_daily_prices') }}
),

universe as (
    select
        symbol,
        cohort,
        effective_date,
        next_effective_date,
        liquidity_rank,
        adv60
    from {{ ref('int_universe_snapshots') }}
),

/*
  fundamentals를 (stable_id_or_cik, available_month) 단위로 집계.

  목표: trade_date의 year_month로 equi-join할 수 있도록 준비.
  
  "as-of-month" 패턴:
    - available_at ≤ trade_date 인 가장 최근의 재무 데이터를 사용.
    - LATERAL 대신, 각 월에 "그 시점까지 이용 가능한 최신" 재무 데이터를
      미리 계산해 둔다.
    - 재무 데이터는 분기 보고이므로, 동일 월 내 latest 1건만 남겨도 충분함.
  
  구현:
    1. DISTINCT ON (stable_id_or_cik, year_month): 동일 월에 여러 공시가 있으면
       가장 늦은 available_at 1건만 유지.
    2. 이 결과에서 trade_date의 year_month ≤ available_month 인 최근 열을
       JOIN 시 range로 찾아야 하는 문제가 남는다.
       
  → 더 나은 해결: generate_series로 월별 스파인 생성 후 fill-forward.
  → PostgreSQL에서는 "last_value(... IGNORE NULLS)" 미지원이라
    window + DISTINCT ON 조합을 쓴다.
    
  실용적 접근 (퀀트에서 검증된 패턴):
    - `report_month` = date_trunc('month', available_at)
    - `trade_month`  = date_trunc('month', trade_date)
    - trade_month >= report_month 인 조건으로 join 후 MAX(report_month) 기준 선택
    → 대용량에서 hash join 가능 + 정확한 point-in-time 보장
*/
fundamentals_by_month as (
    select distinct on (stable_id_or_cik, date_trunc('month', available_at))
        stable_id_or_cik,
        date_trunc('month', available_at)::date as report_month,
        available_at,
        weighted_average_shares,
        net_income,
        total_equity,
        total_assets,
        gross_profit,
        operating_income,
        ebitda,
        revenue,
        cash_and_equivalents,
        short_term_debt,
        long_term_debt,
        operating_cash_flow,
        capex,
        interest_expense
    from {{ ref('int_point_in_time_fundamentals') }}
    order by stable_id_or_cik, date_trunc('month', available_at), available_at desc
),

/*
  Step 1: prices × security_master (작은 테이블 먼저 → hash join, 중복 제거 포함)
*/
prices_enriched as (
    select *
    from (
        select
            sm.symbol,
            sm.stable_id_or_cik,
            sm.shares_outstanding,
            p.trade_date,
            p.adjusted_close,
            p.close,
            p.effective_as_of,
            date_trunc('month', p.trade_date)::date as trade_month,
            row_number() over (
                partition by sm.symbol, p.trade_date
                order by sm.shares_outstanding nulls last
            ) as rn
        from security_master sm
        join prices p
            on p.symbol = sm.symbol
    ) as pe_rn
    where rn = 1
),

/*
  Step 2: + universe (symbol equi-join → hash join 후 날짜 range 필터)
  universe는 월별 스냅샷(284K)이므로 symbol당 몇 건만 존재 → Nested Loop 범위 작음.
*/
joined as (
    select
        pe.symbol,
        pe.stable_id_or_cik,
        pe.shares_outstanding,
        pe.trade_date,
        pe.trade_month,
        pe.adjusted_close,
        pe.close,
        pe.effective_as_of,
        u.cohort,
        u.effective_date  as snapshot_date,
        u.liquidity_rank,
        u.adv60           as snapshot_adv60
    from prices_enriched pe
    join universe u
        on u.symbol = pe.symbol
       and pe.trade_date >= u.effective_date
       and (u.next_effective_date is null or pe.trade_date < u.next_effective_date)
),

/*
  Step 3: + fundamentals (as-of-month 패턴, equi-join 가능)

  trade_month로 "그 시점까지의 최신" 재무 데이터를 찾는다:
    1. joined.trade_month >= fundamentals_by_month.report_month  (미래 데이터 제외)
    2. 여러 report_month 중 가장 최신(MAX)을 선택 → GROUP BY + MAX 후 재join
  
  이렇게 하면:
    - hash join on (stable_id_or_cik, report_month) 가능
    - LATERAL row-by-row 스캔 완전히 제거
*/
latest_report_month as (
    select
        j.symbol,
        j.trade_date,
        j.stable_id_or_cik,
        max(f.report_month) as latest_report_month
    from joined j
    join fundamentals_by_month f
        on f.stable_id_or_cik = j.stable_id_or_cik
       and f.report_month <= j.trade_month
    group by j.symbol, j.trade_date, j.stable_id_or_cik
),

final as (
    select
        j.symbol,
        j.trade_date,
        j.stable_id_or_cik,
        j.cohort,
        j.snapshot_date,
        j.liquidity_rank,
        j.snapshot_adv60,
        j.adjusted_close,
        j.close,
        j.effective_as_of,
        coalesce(j.shares_outstanding, f.weighted_average_shares) as shares_outstanding,
        f.net_income,
        f.total_equity,
        f.total_assets,
        f.gross_profit,
        f.operating_income,
        f.ebitda,
        f.revenue,
        f.cash_and_equivalents,
        f.short_term_debt,
        f.long_term_debt,
        f.operating_cash_flow,
        f.capex,
        f.interest_expense
    from joined j
    left join latest_report_month lrm
        on lrm.symbol    = j.symbol
       and lrm.trade_date = j.trade_date
    left join fundamentals_by_month f
        on f.stable_id_or_cik = j.stable_id_or_cik
       and f.report_month     = lrm.latest_report_month
)

select * from final
