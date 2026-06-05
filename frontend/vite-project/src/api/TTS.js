import { apiPost } from './apiClient.js';

export const getTTS = async (text) => {
    const response = await apiPost('/tts', 
        { text }, 
        { 
            responseType: 'blob' // 接收音頻數據為 blob 格式
        }
    );
    return response.data; // 返回 blob 數據
}

