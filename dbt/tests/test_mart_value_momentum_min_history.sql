select *
from {{ ref('mart_value_momentum_inputs') }}
where momentum_12_1 is not null
  and lookback_observations < 273
