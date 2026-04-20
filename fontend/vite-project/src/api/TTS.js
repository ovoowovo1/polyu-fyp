import axios from 'axios';
import { API_BASE_URL } from '../config.js';

export const getTTS = async (text) => {
    console.log('[TTS] 發送請求，text 類型:', typeof text, '值:', text);
    const response = await axios.post(`${API_BASE_URL}/tts`, 
        { text }, 
        { 
            responseType: 'blob' // 接收音頻數據為 blob 格式
        }
    );
    return response.data; // 返回 blob 數據
}



