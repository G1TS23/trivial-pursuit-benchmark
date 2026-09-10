-- Question métier : quel modèle répond le mieux, et à quel coût de latence ?
select
    model,
    prompt_id,
    count(*)                                          as n_questions,
    avg(ai_correct::int)                              as accuracy,
    sum(ai_correct::int)                              as n_correct,
    avg(is_parsable::int)                             as parsable_rate,
    median(response_time)                             as median_response_time_s,
    avg(response_time)                                as mean_response_time_s,
    avg(tokens_per_second)                            as mean_tokens_per_second,
    avg(answer_len)                                   as mean_answer_len
from {{ ref('fct_benchmark_results') }}
group by model, prompt_id
order by accuracy desc
