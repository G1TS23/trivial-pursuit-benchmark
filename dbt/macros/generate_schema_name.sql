{#
  Par défaut dbt préfixe les schémas custom avec le schéma cible
  (target.schema=main -> "main_marts", "main_staging"). On veut des schémas
  "marts" / "staging" tout courts (utilisés tels quels dans le dashboard
  Streamlit et la doc). Override standard recommandé par dbt :
  https://docs.getdbt.com/docs/build/custom-schemas
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
