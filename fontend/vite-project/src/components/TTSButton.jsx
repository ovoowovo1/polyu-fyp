import React, { useState, useRef, useCallback, useEffect } from 'react'
import { SoundOutlined, PauseCircleOutlined } from '@ant-design/icons'
import { Button, message } from 'antd'

import { getTTS } from '../api/TTS'
import extractMessageText from '../utils/extractMessageText'

export default function TTSButton({ text }) {
    const [loading, setLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const audioRef = useRef(null); // 用於保存 Audio 實例
    const audioUrlRef = useRef(null); // 用於保存音頻 URL，以便重複播放

    // 組件卸載時清理資源
    useEffect(() => {
        return () => {
            if (audioUrlRef.current) {
                console.log('[TTSButton] 組件卸載，釋放音頻 URL');
                URL.revokeObjectURL(audioUrlRef.current);
            }
            if (audioRef.current) {
                audioRef.current.pause();
            }
        };
    }, []);

    const processText = useCallback((messageContent) => {
        console.log('[TTSButton] 處理文本，類型:', typeof messageContent, '值:', messageContent);
        const extractedText = extractMessageText(messageContent);
        console.log('[TTSButton] 提取的文本:', extractedText);
        return extractedText;
    }, []);



    const handleTTS = async () => {
        // 如果正在播放，則停止
        if (isPlaying && audioRef.current) {
            audioRef.current.pause();
            audioRef.current.currentTime = 0; // 重置到開始位置
            setIsPlaying(false);
            return;
        }

        // 如果正在加載，不處理
        if (loading) return;

        // 如果已經有緩存的音頻，直接播放
        if (audioRef.current && audioUrlRef.current) {
            console.log('[TTSButton] 使用緩存的音頻');
            try {
                audioRef.current.currentTime = 0; // 從頭播放
                await audioRef.current.play();
                setIsPlaying(true);
                return;
            } catch (err) {
                console.error('[TTSButton] 播放緩存音頻失敗:', err);
                // 如果播放失敗，繼續生成新音頻
            }
        }

        try {
            setLoading(true);

            // 處理文本，提取純文本內容
            const processedText = processText(text);
            
            if (!processedText || !processedText.trim()) {
                message.warning('沒有可轉換的文本內容');
                return;
            }
            
            // 獲取音頻 blob 數據
            const audioBlob = await getTTS(processedText);
            
            console.log('[TTSButton] 收到的 blob 類型:', audioBlob.type, '大小:', audioBlob.size);

            // 如果有舊的 URL，先釋放
            if (audioUrlRef.current) {
                URL.revokeObjectURL(audioUrlRef.current);
            }

            // 創建新的音頻 URL
            const audioUrl = URL.createObjectURL(audioBlob);
            audioUrlRef.current = audioUrl;

            // 創建新的 Audio 實例
            const audio = new Audio(audioUrl);
            audioRef.current = audio;

            // 添加詳細的事件監聽器來調試
            audio.onloadedmetadata = () => {
                console.log('[TTSButton] 音頻元數據已加載:', {
                    duration: audio.duration,
                    readyState: audio.readyState
                });
                
                // 如果音頻太短，警告用戶
                if (audio.duration < 1) {
                    console.warn('[TTSButton] 警告：音頻時長很短 (<1秒)，可能文本太少');
                }
            };

            audio.oncanplay = () => {
                console.log('[TTSButton] 音頻可以播放');
            };

            audio.oncanplaythrough = () => {
                console.log('[TTSButton] 音頻可以完整播放');
            };

            // 播放結束時的處理
            audio.onended = () => {
                console.log('[TTSButton] 播放結束');
                setIsPlaying(false);
                // 不釋放 URL，以便重複播放
            };

            // 播放錯誤處理
            audio.onerror = (e) => {
                console.error('[TTSButton] 音頻錯誤:', e);
                console.error('[TTSButton] Audio error details:', {
                    error: audio.error,
                    code: audio.error?.code,
                    message: audio.error?.message,
                    networkState: audio.networkState,
                    readyState: audio.readyState
                });
                message.error('音頻播放失敗');
                setIsPlaying(false);
                // 發生錯誤時清除緩存，下次重新生成
                if (audioUrlRef.current) {
                    URL.revokeObjectURL(audioUrlRef.current);
                    audioUrlRef.current = null;
                }
                audioRef.current = null;
            };

            // 開始播放
            console.log('[TTSButton] 嘗試播放音頻...');
            await audio.play();
            setIsPlaying(true);
            console.log('[TTSButton] 播放已開始');

        } catch (error) {
            console.error('TTS 錯誤:', error);
            message.error('語音生成失敗，請稍後再試');
        } finally {
            setLoading(false);
        }
    }

    return (
        <Button
            type="text"
            size="small"
            icon={isPlaying ? <PauseCircleOutlined /> : <SoundOutlined />}
            title={isPlaying ? "停止播放" : "語音播放"}
            loading={loading}
            onClick={handleTTS}
        />
    )
}
