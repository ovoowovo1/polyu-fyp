import axios from 'axios';
import { API_BASE_URL } from '../config.js';
import { getToken } from './auth';

/**
 * 獲取帶認證的 axios 配置
 */
const getAuthConfig = () => {
    const token = getToken();
    return token ? { headers: { Authorization: `Bearer ${token}` } } : {};
};

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
    const config = getAuthConfig();
    console.log('[Exam API] 發送考試生成請求:', params);
    
    return axios.post(`${API_BASE_URL}/exam/generate`, params, config);
};

/**
 * 只生成題目，不生成 PDF
 * @param {Object} params - 同 generateExam
 * @returns {Promise} - API 響應
 */
export const generateQuestionsOnly = async (params) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/generate-questions-only`, params, config);
};

/**
 * 重新生成 PDF
 * @param {string} examId - 考試 ID
 * @param {Array} questions - 題目列表
 * @param {string} examName - 考試名稱
 * @returns {Promise} - API 響應
 */
export const regenerateExamPdf = async (examId, questions, examName) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/${examId}/regenerate-pdf`, {
        questions,
        exam_name: examName
    }, config);
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
    const config = getAuthConfig();
    const response = await axios.get(`${API_BASE_URL}/exam/${examId}/pdf`, {
        ...config,
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
    return axios.get(`${API_BASE_URL}/exam/difficulties`);
};

/**
 * 獲取支援的題目類型
 * @returns {Promise} - 題目類型列表
 */
export const getQuestionTypes = async () => {
    return axios.get(`${API_BASE_URL}/exam/question-types`);
};

/**
 * 取得考試列表（依班級）
 * @param {string} classId
 */
export const getExamList = async (classId) => {
    const config = getAuthConfig();
    return axios.get(`${API_BASE_URL}/exam/list`, { params: { class_id: classId }, ...config });
};

/**
 * 取得考試詳情
 * @param {string} examId
 * @param {boolean} includeAnswers
 */
export const getExamById = async (examId, includeAnswers = false) => {
    const config = getAuthConfig();
    return axios.get(`${API_BASE_URL}/exam/${examId}`, { params: { include_answers: includeAnswers }, ...config });
};

/**
 * 更新考試
 * @param {string} examId
 * @param {object} data
 */
export const updateExam = async (examId, data) => {
    const config = getAuthConfig();
    return axios.put(`${API_BASE_URL}/exam/${examId}`, data, config);
};

/**
 * 刪除考試
 * @param {string} examId
 */
export const deleteExam = async (examId) => {
    const config = getAuthConfig();
    return axios.delete(`${API_BASE_URL}/exam/${examId}`, config);
};

/**
 * 發布/取消發布考試
 * @param {string} examId
 * @param {boolean} isPublished
 */
export const publishExam = async (examId, isPublished = true) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/${examId}/publish`, { is_published: isPublished }, config);
};

/**
 * 學生開始作答
 * @param {string} examId
 */
export const startExam = async (examId) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/${examId}/start`, {}, config);
};

/**
 * 學生提交答案
 * @param {string} submissionId
 * @param {object} data - { answers: [...], time_spent_seconds?: number }
 */
export const submitExam = async (submissionId, data) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/submission/${submissionId}/submit`, data, config);
};

/**
 * 老師查看所有提交
 * @param {string} examId
 */
export const getExamSubmissions = async (examId) => {
    const config = getAuthConfig();
    return axios.get(`${API_BASE_URL}/exam/${examId}/submissions`, config);
};

/**
 * 學生查看自己的提交
 * @param {string} examId
 */
export const getMyExamSubmissions = async (examId) => {
    const config = getAuthConfig();
    return axios.get(`${API_BASE_URL}/exam/${examId}/my-submissions`, config);
};

/**
 * 老師批改提交
 * @param {string} submissionId
 * @param {object} data - { answers_grades: [...], teacher_comment?: string }
 */
export const gradeSubmission = async (submissionId, data) => {
    const config = getAuthConfig();
    return axios.put(`${API_BASE_URL}/exam/submission/${submissionId}/grade`, data, config);
};

/**
 * AI auto-grade submission
 * @param {string} submissionId
 * @returns {Promise} - { message, submission, graded_answers }
 */
export const aiGradeSubmission = async (submissionId) => {
    const config = getAuthConfig();
    return axios.post(`${API_BASE_URL}/exam/submission/${submissionId}/ai-grade`, {}, config);
};

