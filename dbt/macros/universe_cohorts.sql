{% macro get_universe_cohort() %}
  {{ return(env_var('DBT_UNIVERSE_COHORT', 'us_liquidity_700_v1')) }}
{% endmacro %}

{% macro get_buffer_cohort() %}
  {{ return(env_var('DBT_BUFFER_COHORT', 'us_liquidity_900_buffer_v1')) }}
{% endmacro %}
