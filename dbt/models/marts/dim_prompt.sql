select
    prompt_id,
    any_value(prompt_mode)                as prompt_mode,
    any_value(raw_answer) is not null     as has_samples,
    count(*)                              as n_responses
from {{ ref('stg_responses') }}
group by prompt_id
