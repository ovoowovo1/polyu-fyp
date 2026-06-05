import { API_BASE_URL } from '../config.js';
import { apiDelete, apiGet, apiPost, apiPut } from './apiClient.js';

/**
 * 使用 Multi-Agent 系統生成考試（含 PDF）
 * @param {Object} params - 生成參數
 * @param {Array<string>} params.file_ids - 文件 ID 列表
 * @param {string} params.topic - 考試主題（可選）
 * @param {string} params.difficulty - 難度 (easy/medium/difficult)
 * @param {number} params.num_questions - 題目數量
 * @param {string} params.exam_name - 考試名稱（可選）
 * @param {boolean} params.include_images - 是否包含圖表
 * @returns {Promise} - API 響應
 */
export const generateExam = async (params) => {
    return apiPost('/exam/generate', params);
};

/**
 * 只生成題目，不生成 PDF
 * @param {Object} params - 同 generateExam
 * @returns {Promise} - API 響應
 */
export const generateQuestionsOnly = async (params) => {
    return apiPost('/exam/generate-questions-only', params);
};

/**
 * 重新生成 PDF
 * @param {string} examId - 考試 ID
 * @param {Array} questions - 題目列表
 * @param {string} examName - 考試名稱
 * @returns {Promise} - API 響應
 */
export const regenerateExamPdf = async (examId, questions, examName) => {
    return apiPost(`/exam/${examId}/regenerate-pdf`, {
        questions,
        exam_name: examName
    });
};

/**
 * 獲取考試 PDF 下載 URL
 * @param {string} examId - 考試 ID
 * @returns {string} - PDF URL
 */
export const getExamPdfUrl = (examId) => {
    return `${API_BASE_URL}/exam/${examId}/pdf`;
};

/**
 * 下載考試 PDF
 * @param {string} examId - 考試 ID
 * @param {string} filename - 下載的檔案名稱
 */
export const downloadExamPdf = async (examId, filename = 'exam.pdf') => {
    const response = await apiGet(`/exam/${examId}/pdf`, {
        responseType: 'blob'
    });
    
    // 創建下載連結
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
};

/**
 * 獲取考試難度選項
 * @returns {Promise} - 難度選項列表
 */
export const getExamDifficulties = async () => {
    return apiGet('/exam/difficulties');
};

/**
 * 獲取支援的題目類型
 * @returns {Promise} - 題目類型列表
 */
export const getQuestionTypes = async () => {
    return apiGet('/exam/question-types');
};

/**
 * 取得考試列表（依班級）
 * @param {string} classId
 */
export const getExamList = async (classId) => {
    return apiGet('/exam/list', { params: { class_id: classId } });
};

/**
 * 取得考試詳情
 * @param {string} examId
 * @param {boolean} includeAnswers
 */
export const getExamById = async (examId, includeAnswers = false) => {
    return apiGet(`/exam/${examId}`, { params: { include_answers: includeAnswers } });
};

/**
 * 更新考試
 * @param {string} examId
 * @param {object} data
 */
export const updateExam = async (examId, data) => {
    return apiPut(`/exam/${examId}`, data);
};

/**
 * 刪除考試
 * @param {string} examId
 */
export const deleteExam = async (examId) => {
    return apiDelete(`/exam/${examId}`);
};

/**
 * 發布/取消發布考試
 * @param {string} examId
 * @param {boolean} isPublished
 */
export const publishExam = async (examId, isPublished = true) => {
    return apiPost(`/exam/${examId}/publish`, { is_published: isPublished });
};

/**
 * 學生開始作答
 * @param {string} examId
 */
export const startExam = async (examId) => {
    return apiPost(`/exam/${examId}/start`, {});
};

/**
 * 學生提交答案
 * @param {string} submissionId
 * @param {object} data - { answers: [...], time_spent_seconds?: number }
 */
export const submitExam = async (submissionId, data) => {
    return apiPost(`/exam/submission/${submissionId}/submit`, data);
};

/**
 * 老師查看所有提交
 * @param {string} examId
 */
export const getExamSubmissions = async (examId) => {
    return apiGet(`/exam/${examId}/submissions`);
};

/**
 * 學生查看自己的提交
 * @param {string} examId
 */
export const getMyExamSubmissions = async (examId) => {
    return apiGet(`/exam/${examId}/my-submissions`);
};

/**
 * 老師批改提交
 * @param {string} submissionId
 * @param {object} data - { answers_grades: [...], teacher_comment?: string }
 */
export const gradeSubmission = async (submissionId, data) => {
    return apiPut(`/exam/submission/${submissionId}/grade`, data);
};

/**
 * AI auto-grade submission
 * @param {string} submissionId
 * @returns {Promise} - { message, submission, graded_answers }
 */
export const aiGradeSubmission = async (submissionId) => {
    return apiPost(`/exam/submission/${submissionId}/ai-grade`, {});
};
