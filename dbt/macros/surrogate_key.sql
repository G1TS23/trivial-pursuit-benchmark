{#
  Clé de substitution : md5 des champs concaténés (NULL -> '_null_').
  Remplace dbt_utils.generate_surrogate_key : évite le paquet externe, donc
  l'étape `dbt deps` (qui exige internet) pour qui clone le dépôt.
#}
{% macro surrogate_key(field_list) -%}
md5(
    {%- for f in field_list -%}
        coalesce(cast({{ f }} as varchar), '_null_')
        {%- if not loop.last %} || '-' || {% endif -%}
    {%- endfor -%}
)
{%- endmacro %}
