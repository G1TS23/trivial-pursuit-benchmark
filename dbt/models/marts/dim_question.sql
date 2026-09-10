select
    question_id,
    category,
    question_type,
    difficulty,
    question_text,
    correct_answer,
    correct_letter,
    n_options,
    question_len,
    -- baseline "au hasard" pour comparer la performance des modèles
    1.0 / n_options as random_baseline
from {{ ref('stg_questions') }}
