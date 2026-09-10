-- Question métier : qu'apporte chaque formulation de prompt, à modèle fixé ?
-- (précision ET part de réponses exploitables, souvent le vrai gain du "bon" prompt)
with per_prompt as (
    select
        model,
        prompt_id,
        prompt_mode,
        avg(ai_correct::int)   as accuracy,
        avg(is_parsable::int)  as parsable_rate,
        avg(answer_len)        as mean_answer_len,
        median(response_time)  as median_response_time_s
    from {{ ref('fct_benchmark_results') }}
    group by model, prompt_id, prompt_mode
),
baseline as (
    select model, accuracy as base_accuracy
    from per_prompt
    where prompt_id = 'p1_naif'
)

select
    p.*,
    p.accuracy - b.base_accuracy as accuracy_vs_naif
from per_prompt p
left join baseline b using (model)
order by p.model, p.accuracy desc
