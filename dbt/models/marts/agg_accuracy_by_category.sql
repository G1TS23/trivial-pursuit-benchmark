-- Question métier : forces / angles morts thématiques de chaque modèle.
select
    model,
    prompt_id,
    category,
    count(*)               as n_questions,
    avg(ai_correct::int)    as accuracy,
    median(response_time)   as median_response_time_s
from {{ ref('fct_benchmark_results') }}
group by model, prompt_id, category
order by model, prompt_id, accuracy desc
