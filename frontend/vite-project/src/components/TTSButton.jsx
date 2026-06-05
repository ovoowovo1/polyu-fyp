import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PauseCircleOutlined, SoundOutlined } from '@ant-design/icons';
import { Button, message } from 'antd';

import { getTTS } from '../api/TTS';
import extractMessageText from '../utils/extractMessageText';

export default function TTSButton({ text }) {
    const [loading, setLoading] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const audioRef = useRef(null);
    const audioUrlRef = useRef(null);

    useEffect(() => () => {
        if (audioUrlRef.current) {
            URL.revokeObjectURL(audioUrlRef.current);
        }
        if (audioRef.current) {
            audioRef.current.pause();
        }
    }, []);

    const processText = useCallback((messageContent) => extractMessageText(messageContent), []);

    const playCachedAudio = async () => {
        if (!audioRef.current || !audioUrlRef.current) {
            return false;
        }
        try {
            audioRef.current.currentTime = 0;
            await audioRef.current.play();
            setIsPlaying(true);
            return true;
        } catch (error) {
            console.error('[TTSButton] Failed to play cached audio:', error);
            return false;
        }
    };

    const resetAudio = () => {
        if (audioUrlRef.current) {
            URL.revokeObjectURL(audioUrlRef.current);
            audioUrlRef.current = null;
        }
        audioRef.current = null;
        setIsPlaying(false);
    };

    const handleTTS = async () => {
        if (isPlaying && audioRef.current) {
            audioRef.current.pause();
            audioRef.current.currentTime = 0;
            setIsPlaying(false);
            return;
        }

        if (loading) return;
        if (await playCachedAudio()) return;

        try {
            setLoading(true);
            const processedText = processText(text);

            if (!processedText.trim()) {
                message.warning('No readable text available for speech.');
                return;
            }

            const audioBlob = await getTTS(processedText);
            resetAudio();

            const audioUrl = URL.createObjectURL(audioBlob);
            audioUrlRef.current = audioUrl;

            const audio = new Audio(audioUrl);
            audioRef.current = audio;
            audio.onended = () => setIsPlaying(false);
            audio.onerror = (event) => {
                console.error('[TTSButton] Audio playback failed:', event);
                message.error('Audio playback failed.');
                resetAudio();
            };

            await audio.play();
            setIsPlaying(true);
        } catch (error) {
            console.error('TTS failed:', error);
            message.error('Failed to generate speech. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Button
            type="text"
            size="small"
            icon={isPlaying ? <PauseCircleOutlined /> : <SoundOutlined />}
            title={isPlaying ? 'Pause speech' : 'Play speech'}
            loading={loading}
            onClick={handleTTS}
        />
    );
}
