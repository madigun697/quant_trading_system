select *
from {{ ref('int_prices_universe_daily') }}
where fundamentals_available_at is not null
  and fundamentals_available_at::date > trade_date
