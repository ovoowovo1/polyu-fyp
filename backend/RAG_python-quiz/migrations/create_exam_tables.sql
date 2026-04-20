-- =====================================================
-- 考試系統資料表遷移腳本
-- Migration: create_exam_tables.sql
-- Description: 創建考試、考試題目、考試提交、考試答案相關資料表
-- =====================================================

-- 1. 創建 exams 表（考試主表）
CREATE TABLE IF NOT EXISTS exams (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id            uuid        REFERENCES classes(id) ON DELETE SET NULL,
    owner_id            uuid        REFERENCES teachers(user_id) ON DELETE SET NULL,
    title               text        NOT NULL,
    description         text        DEFAULT NULL,
    duration_minutes    int         DEFAULT NULL,  -- NULL 表示無時間限制
    is_published        boolean     NOT NULL DEFAULT false,
    start_at            timestamptz DEFAULT NULL,  -- 考試開始時間
    end_at              timestamptz DEFAULT NULL,  -- 考試結束時間
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    
    -- 額外欄位（用於存儲生成相關資訊）
    difficulty          text        DEFAULT 'medium',
    total_marks         int         DEFAULT 0,
    pdf_path            text        DEFAULT NULL,
    questions_json      jsonb       DEFAULT '[]'::jsonb  -- 備份用，主要題目存在 exam_questions
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_exams_class_id ON exams(class_id);
CREATE INDEX IF NOT EXISTS idx_exams_owner_id ON exams(owner_id);
CREATE INDEX IF NOT EXISTS idx_exams_created_at ON exams(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exams_is_published ON exams(is_published);

COMMENT ON TABLE exams IS '考試主表';
COMMENT ON COLUMN exams.owner_id IS '創建考試的老師 ID';
COMMENT ON COLUMN exams.duration_minutes IS '考試時間限制（分鐘），NULL 表示無限制';
COMMENT ON COLUMN exams.is_published IS '是否已發布給學生';
COMMENT ON COLUMN exams.start_at IS '考試開放開始時間';
COMMENT ON COLUMN exams.end_at IS '考試開放結束時間';


-- 2. 創建 exam_questions 表（考試題目）
CREATE TABLE IF NOT EXISTS exam_questions (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id             uuid        NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    position            int         NOT NULL DEFAULT 0,  -- 題目順序
    question_snapshot   jsonb       NOT NULL,  -- 題目完整資訊的快照
    max_marks           int         NOT NULL DEFAULT 1,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_exam_questions_exam_id ON exam_questions(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_questions_position ON exam_questions(exam_id, position);

COMMENT ON TABLE exam_questions IS '考試題目表';
COMMENT ON COLUMN exam_questions.position IS '題目在考試中的順序（從 0 開始）';
COMMENT ON COLUMN exam_questions.question_snapshot IS '題目的完整 JSON 快照，包含 question_id, question_type, question_text, choices, correct_answer_index, model_answer, marking_scheme, rationale, image_path 等';
COMMENT ON COLUMN exam_questions.max_marks IS '該題滿分';


-- 3. 創建 exam_documents 表（考試與來源文件的關聯）
CREATE TABLE IF NOT EXISTS exam_documents (
    exam_id     uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (exam_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_exam_documents_document_id ON exam_documents(document_id);

COMMENT ON TABLE exam_documents IS '考試與來源文件的關聯表';


-- 4. 創建 exam_submissions 表（學生考試提交）
CREATE TABLE IF NOT EXISTS exam_submissions (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_id             uuid        NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    student_id          uuid        NOT NULL REFERENCES students(user_id) ON DELETE CASCADE,
    started_at          timestamptz NOT NULL DEFAULT now(),
    submitted_at        timestamptz DEFAULT NULL,
    status              text        NOT NULL DEFAULT 'in_progress',  -- in_progress, submitted, graded
    meta                jsonb       DEFAULT '{}'::jsonb,  -- 額外元資料
    created_at          timestamptz NOT NULL DEFAULT now(),
    
    -- 額外欄位
    attempt_no          int         NOT NULL DEFAULT 1,
    score               int         DEFAULT NULL,
    total_marks         int         DEFAULT NULL,
    time_spent_seconds  int         DEFAULT NULL,
    teacher_comment     text        DEFAULT NULL,
    graded_by           uuid        REFERENCES teachers(user_id) ON DELETE SET NULL,
    graded_at           timestamptz DEFAULT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_id ON exam_submissions(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_student_id ON exam_submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_exam_student ON exam_submissions(exam_id, student_id);
CREATE INDEX IF NOT EXISTS idx_exam_submissions_status ON exam_submissions(status);

COMMENT ON TABLE exam_submissions IS '學生考試提交記錄';
COMMENT ON COLUMN exam_submissions.status IS '狀態: in_progress(作答中), submitted(已提交), graded(已批改)';
COMMENT ON COLUMN exam_submissions.meta IS '額外元資料 JSON，如瀏覽器資訊、IP 等';
COMMENT ON COLUMN exam_submissions.attempt_no IS '第幾次嘗試作答';


-- 5. 創建 exam_answers 表（學生答案）
CREATE TABLE IF NOT EXISTS exam_answers (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id       uuid        NOT NULL REFERENCES exam_submissions(id) ON DELETE CASCADE,
    exam_question_id    uuid        NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
    question_snapshot   jsonb       DEFAULT NULL,  -- 作答時的題目快照（可選）
    answer_text         text        DEFAULT NULL,  -- 文字答案（簡答題、論述題）
    selected_options    jsonb       DEFAULT NULL,  -- 選擇的選項 [0, 2] 或單選 [1]
    attachments         jsonb       DEFAULT '[]'::jsonb,  -- 附件列表
    created_at          timestamptz NOT NULL DEFAULT now(),
    
    -- 額外欄位
    time_spent_seconds  int         DEFAULT NULL,
    is_correct          boolean     DEFAULT NULL,
    marks_earned        int         DEFAULT NULL,
    teacher_feedback    text        DEFAULT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_exam_answers_submission_id ON exam_answers(submission_id);
CREATE INDEX IF NOT EXISTS idx_exam_answers_question_id ON exam_answers(exam_question_id);

COMMENT ON TABLE exam_answers IS '學生答案表';
COMMENT ON COLUMN exam_answers.selected_options IS '選擇題的選項索引，JSON 陣列格式如 [0] 或多選 [0, 2]';
COMMENT ON COLUMN exam_answers.attachments IS '附件列表，JSON 陣列';
COMMENT ON COLUMN exam_answers.is_correct IS '是否正確（自動批改後填入）';
COMMENT ON COLUMN exam_answers.marks_earned IS '獲得分數';
COMMENT ON COLUMN exam_answers.teacher_feedback IS '老師針對此題的回饋';


-- =====================================================
-- 觸發器：自動更新 exams.updated_at
-- =====================================================
CREATE OR REPLACE FUNCTION update_exams_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_exams_updated_at ON exams;
CREATE TRIGGER trigger_exams_updated_at
    BEFORE UPDATE ON exams
    FOR EACH ROW
    EXECUTE FUNCTION update_exams_updated_at();


-- =====================================================
-- question_snapshot 結構範例
-- =====================================================
/*
{
  "question_id": "q_abc123",
  "question_type": "multiple_choice",  -- multiple_choice, short_answer, essay
  "bloom_level": "understand",
  "question_text": "題目內容...",
  "choices": ["A. 選項1", "B. 選項2", "C. 選項3", "D. 選項4"],
  "correct_answer_index": 0,
  "model_answer": null,  -- 非選擇題的標準答案
  "marks": 2,
  "marking_scheme": [
    {"criterion": "正確選擇", "marks": 2, "explanation": "選對得 2 分"}
  ],
  "rationale": "答案解釋...",
  "image_path": "/static/images/exam_xxx_q_abc123.png",
  "source_chunk_ids": ["chunk_id_1", "chunk_id_2"]
}
*/
