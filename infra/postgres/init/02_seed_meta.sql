insert into meta.fred_series_config (series_id, description, is_active)
values
  ('DGS3MO', '3-Month Treasury Constant Maturity Rate', true)
on conflict (series_id) do update
set description = excluded.description,
    is_active = excluded.is_active;

insert into meta.universe_members (symbol, cohort, is_active, effective_date, source)
values
  ('AAPL', 'prototype', true, current_date, 'seed'),
  ('MSFT', 'prototype', true, current_date, 'seed'),
  ('AMZN', 'prototype', true, current_date, 'seed'),
  ('GOOGL', 'prototype', true, current_date, 'seed'),
  ('META', 'prototype', true, current_date, 'seed'),
  ('NVDA', 'prototype', true, current_date, 'seed'),
  ('BRK.B', 'prototype', true, current_date, 'seed'),
  ('JPM', 'prototype', true, current_date, 'seed'),
  ('XOM', 'prototype', true, current_date, 'seed'),
  ('SPY', 'prototype', true, current_date, 'seed')
on conflict do nothing;
