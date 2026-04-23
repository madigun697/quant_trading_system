{{ config(tags=["int"]) }}

select
    symbol,
    cohort,
    snapshot_date as effective_date,
    lead(snapshot_date) over (
        partition by symbol, cohort
        order by snapshot_date
    ) as next_effective_date,
    liquidity_rank,
    adv60,
    source,
    true as is_active
from {{ ref('int_universe_rank_snapshots') }}
