import axios from 'axios';
import { API_BASE_URL } from '../config.js';
import { dedupe } from '../utils/requestDeduper';
import { getToken } from './auth';


/**
 * 生成測驗題目
 * @param {Array<string>} fileIds - Neo4j 文件 ID 列表
 * @param {Object} options - 可選參數
 * @param {Array<string>} options.bloomLevels - Bloom 認知層級列表
 * @param {string} options.difficulty - 難度級別 (easy/medium/difficult)
 * @param {number} options.numQuestions - 題目數量 (1-50)
 * @returns {Promise} - API 響應
 */
export const generateQuiz = async (fileIds, options = {}) => {
    const formData = new FormData();
    
    // 添加文件 IDs
    fileIds.forEach(id => {
        formData.append('file_ids', id);
    });
    
    // 添加可選參數
    if (options.bloomLevels && options.bloomLevels.length > 0) {
        options.bloomLevels.forEach(level => {
            formData.append('bloom_levels', level);
        });
    }
    
    if (options.difficulty) {
        formData.append('difficulty', options.difficulty);
    }
    
    if (options.numQuestions) {
        formData.append('num_questions', options.numQuestions);
    }
    
    console.log('發送測驗生成請求:', { fileIds, options });
    console.log('FormData entries:');
    for (let pair of formData.entries()) {
        console.log(pair[0] + ': ' + pair[1]);
    }
    
    return axios.post(`${API_BASE_URL}/quiz/generate`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    });
};


/**
 * 獲取所有 Bloom 認知層級
 * @returns {Promise} - Bloom 層級列表
 */
export const getBloomLevels = async () => {
    return axios.get(`${API_BASE_URL}/quiz/bloom-levels`);
};


/**
 * 獲取所有難度級別
 * @returns {Promise} - 難度級別列表
 */
export const getDifficulties = async () => {
    return axios.get(`${API_BASE_URL}/quiz/difficulties`);
};


/**
 * 獲取所有測驗列表
 * @param {string} classId - 班級 ID
 * @returns {Promise} - 測驗列表
 */
export const getAllQuizzes = async (classId, axiosConfig = {}) => {
    const key = `quiz:list:${classId || '__all__'}`;
    console.log(`[api.quiz] getAllQuizzes called, classId=${classId}, key=${key}`);
    // use dedupe utility; we keep a small TTL to merge very close sequential calls
    return dedupe(key, () => axios.get(`${API_BASE_URL}/quiz/list`, {
        params: { class_id: classId },
        ...axiosConfig,
    }), { ttl: 1000 });
};


/**
 * 根據 ID 獲取特定測驗
 * @param {string} quizId - 測驗 ID
 * @returns {Promise} - 測驗詳情
 */
export const getQuizById = async (quizId) => {
    return axios.get(`${API_BASE_URL}/quiz/${quizId}`);
};


/**
 * 刪除測驗
 * @param {string} quizId - 測驗 ID
 * @returns {Promise} - 刪除結果
 */
export const deleteQuiz = async (quizId) => {
    return axios.delete(`${API_BASE_URL}/quiz/${quizId}`);
};

/**
 * 建立新的測驗（教師手動建立或編輯後儲存）
 * @param {Object} quiz - 包含 name, questions (array), file_ids (optional), class_id (optional)
 */
export const createQuiz = async (quiz) => {
    return axios.post(`${API_BASE_URL}/quiz`, quiz);
};

/**
 * 更新現有測驗
 * @param {string} quizId
 * @param {Object} quiz - 同 createQuiz
 */
export const updateQuiz = async (quizId, quiz) => {
    return axios.put(`${API_BASE_URL}/quiz/${quizId}`, quiz);
};

/**
 * 提交測驗
 * @param {string} quizId
 * @param {Object} payload - { answers: [], score: number, total_questions: number }
 */
export const submitQuiz = async (quizId, payload) => {
    const token = getToken();
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    return axios.post(`${API_BASE_URL}/quiz/${quizId}/submit`, payload, config);
};

/**
 * 生成 AI 測驗回饋
 * @param {string} quizId
 * @param {Object} payload - { score, total_questions, percentage, bloom_summary, questions }
 */
export const generateQuizFeedback = async (quizId, payload) => {
    const token = getToken();
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    return axios.post(`${API_BASE_URL}/quiz/${quizId}/feedback`, payload, config);
};

/**
 * 獲取測驗結果（教師專用）
 * @param {string} quizId
 */
export const getQuizResults = async (quizId) => {
    const token = getToken();
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    return axios.get(`${API_BASE_URL}/quiz/${quizId}/results`, config);
};

/**
 * 獲取自己的測驗結果（學生專用）
 * @param {string} quizId
 */
export const getMyQuizResult = async (quizId) => {
    const token = getToken();
    const config = token ? { headers: { Authorization: `Bearer ${token}` } } : {};
    return axios.get(`${API_BASE_URL}/quiz/${quizId}/my-result`, config);
};
