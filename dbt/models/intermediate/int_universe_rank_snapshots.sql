{{ config(tags=["int"]) }}

select
    snapshot_date,
    cohort,
    symbol,
    rank as liquidity_rank,
    adv60,
    eligibility_status,
    source
from {{ source('meta', 'universe_rank_snapshots') }}
where cohort = '{{ get_universe_cohort() }}'
  and eligibility_status = 'selected'
