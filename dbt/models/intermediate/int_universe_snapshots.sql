select
    symbol,
    cohort,
    effective_date,
    source,
    is_active
from {{ source('meta', 'universe_members') }}
where is_active = true
