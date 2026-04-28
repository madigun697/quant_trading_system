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
  3. + fundamentals            → stable_id_or_cik + available_at range join

  mart_value_quality_inputs, mart_quality_lowvol_inputs,
  mart_value_momentum_inputs 이 세 모델 모두 이 테이블에서 참조한다.

  ── PIT 정합성 메모 ─────────────────────────────────────────────────────────
  이전 구현은 available_at 월 단위로 latest row 하나만 남겨 as-of-month join을 했기 때문에
  같은 달의 late filing이 월 초 거래일에 유입되는 lookahead 위험과 coverage 축소가 있었다.

  새 구현은:
    - 같은 available_at timestamp 에 중복 filing 이 있으면 non-null 필드가 가장 많은 1건 선택
    - lead(available_at)로 다음 유효 시작일을 계산
    - trade_date가 [available_date, next_available_date) 범위에 있는 row를 조인
  하여 point-in-time 보장을 유지하면서 coverage를 높인다.
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
    where cohort = '{{ env_var("DBT_UNIVERSE_COHORT") }}'
),

fundamentals_ranked as (
    select
        stable_id_or_cik,
        accession_number,
        period_end,
        filing_date,
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
        interest_expense,
        row_number() over (
            partition by stable_id_or_cik, available_at
            order by
                (
                    (weighted_average_shares is not null)::int
                    + (net_income is not null)::int
                    + (total_equity is not null)::int
                    + (total_assets is not null)::int
                    + (gross_profit is not null)::int
                    + (operating_income is not null)::int
                    + (ebitda is not null)::int
                    + (revenue is not null)::int
                    + (cash_and_equivalents is not null)::int
                    + (short_term_debt is not null)::int
                    + (long_term_debt is not null)::int
                    + (operating_cash_flow is not null)::int
                    + (capex is not null)::int
                    + (interest_expense is not null)::int
                ) desc,
                filing_date desc,
                accession_number desc
        ) as same_timestamp_rank
    from {{ ref('int_point_in_time_fundamentals') }}
),

fundamentals_timeline as (
    select
        stable_id_or_cik,
        accession_number,
        period_end,
        filing_date,
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
    from fundamentals_ranked
    where same_timestamp_rank = 1
),

fundamentals_periods as (
    select
        stable_id_or_cik,
        accession_number,
        period_end,
        filing_date,
        available_at,
        available_at::date as available_date,
        lead(available_at::date) over (
            partition by stable_id_or_cik
            order by available_at, filing_date, accession_number
        ) as next_available_date,
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
    from fundamentals_timeline
),

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

joined as (
    select
        pe.symbol,
        pe.stable_id_or_cik,
        pe.shares_outstanding,
        pe.trade_date,
        pe.adjusted_close,
        pe.close,
        pe.effective_as_of,
        u.cohort,
        u.effective_date as snapshot_date,
        u.liquidity_rank,
        u.adv60 as snapshot_adv60
    from prices_enriched pe
    join universe u
        on u.symbol = pe.symbol
       and pe.trade_date >= u.effective_date
       and (u.next_effective_date is null or pe.trade_date < u.next_effective_date)
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
        f.available_at as fundamentals_available_at,
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
    left join fundamentals_periods f
        on f.stable_id_or_cik = j.stable_id_or_cik
       and j.trade_date >= f.available_date
       and (f.next_available_date is null or j.trade_date < f.next_available_date)
)

select * from final
