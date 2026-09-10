-- Question métier : la performance tient-elle sur les questions difficiles,
-- et de combien bat-elle le hasard ?
select
    f.model,
    f.prompt_id,
    f.difficulty,
    count(*)                        as n_questions,
    avg(f.ai_correct::int)          as accuracy,
    avg(1.0 / f.n_options)          as random_baseline,
    avg(f.ai_correct::int) - avg(1.0 / f.n_options) as lift_vs_random,
    median(f.response_time)         as median_response_time_s
from {{ ref('fct_benchmark_results') }} f
group by f.model, f.prompt_id, f.difficulty
order by f.model, f.prompt_id, f.difficulty
