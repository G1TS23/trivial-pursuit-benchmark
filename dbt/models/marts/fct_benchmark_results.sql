-- Table de faits du benchmark.
-- Grain : une réponse = (question_id, model, prompt_id, run_id).
with r as (
    select * from {{ ref('stg_responses') }}
),
q as (
    select * from {{ ref('stg_questions') }}
)

select
    {{ surrogate_key(['r.question_id', 'r.model', 'r.prompt_id', 'r.run_id']) }} as result_key,
    r.question_id,
    r.model,
    r.prompt_id,
    r.prompt_mode,
    r.run_id,
    r.ran_at,

    q.category,
    q.question_type,
    q.difficulty,
    q.n_options,
    q.question_len,
    q.question_text,
    q.correct_answer,
    q.correct_letter,
    q.options,

    r.raw_answer,
    r.ai_answer,
    r.ai_correct,
    r.is_parsable,
    r.answer_len,
    r.match_method,

    r.response_time,
    r.gen_time_sec,
    r.ttft_sec,
    r.tokens_per_second
from r
inner join q using (question_id)
