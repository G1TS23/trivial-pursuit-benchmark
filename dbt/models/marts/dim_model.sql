-- Dimension modèle. Enrichissable manuellement via un seed (seeds/model_meta.csv :
-- model, params_b, quantization, family) puis left join ici.
with used as (
    select distinct model from {{ ref('stg_responses') }}
)

select
    model,
    model as model_label
from used
