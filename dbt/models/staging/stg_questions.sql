with src as (
    select * from {{ source('silver', 'questions') }}
)

select
    question_id,
    category,
    type            as question_type,
    difficulty,
    question        as question_text,
    correct_answer,
    correct_letter,
    n_options,
    question_len,
    scraped_at
from src
