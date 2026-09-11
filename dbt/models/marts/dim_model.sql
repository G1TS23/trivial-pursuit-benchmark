-- Dimension modèle : les modèles réellement benchmarkés (stg_responses),
-- enrichis des attributs statiques du seed seeds/model_meta.csv (famille,
-- éditeur, taille, quantization). left join : un modèle sans ligne dans le
-- seed reste dans dim_model, juste avec ces colonnes à NULL.
with used as (
    select distinct model from {{ ref('stg_responses') }}
),
meta as (
    select * from {{ ref('model_meta') }}
)

select
    used.model,
    used.model as model_label,
    meta.family,
    meta.publisher,
    meta.params_b,
    meta.context_window,
    meta.quantization,
    meta.file_size_gb
from used
left join meta using (model)
