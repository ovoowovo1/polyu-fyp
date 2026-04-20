-- Migration: Add grading_source column to exam_submissions
-- This column distinguishes between AI grading and teacher grading

ALTER TABLE exam_submissions 
ADD COLUMN IF NOT EXISTS grading_source text DEFAULT NULL 
CHECK (grading_source IS NULL OR grading_source IN ('ai', 'teacher'));

-- Add comment for documentation
COMMENT ON COLUMN exam_submissions.grading_source IS 'Source of grading: ai = AI auto-graded, teacher = manually graded by teacher';

-- Update status check to include ai_graded
-- Note: If there's an existing CHECK constraint on status, you may need to drop and recreate it
-- ALTER TABLE exam_submissions DROP CONSTRAINT IF EXISTS exam_submissions_status_check;
-- ALTER TABLE exam_submissions ADD CONSTRAINT exam_submissions_status_check 
--   CHECK (status IN ('in_progress', 'submitted', 'graded', 'ai_graded'));
