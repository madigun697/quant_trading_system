{% macro get_universe_cohort() %}
  {{ return(env_var('DBT_UNIVERSE_COHORT', 'us_liquidity_1000_v1')) }}
{% endmacro %}

{% macro get_buffer_cohort() %}
  {{ return(env_var('DBT_BUFFER_COHORT', 'us_liquidity_1500_buffer_v1')) }}
{% endmacro %}
