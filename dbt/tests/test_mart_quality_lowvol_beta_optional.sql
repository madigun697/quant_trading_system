select *
from {{ ref('mart_quality_lowvol_inputs') }}
where beta_252d_optional is not null
  and rolling_vol_252d is null
