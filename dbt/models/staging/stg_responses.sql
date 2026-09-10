with src as (
    select * from {{ source('silver', 'responses') }}
)

select
    question_id,
    model,
    prompt_id,
    prompt_mode,
    run_id,
    ran_at,
    raw_answer,
    ai_answer,
    cast(ai_correct as boolean)   as ai_correct,
    cast(is_parsable as boolean)  as is_parsable,
    answer_len,
    match_method,
    response_time,
    gen_time_sec,
    ttft_sec,
    tokens_per_second
from src
