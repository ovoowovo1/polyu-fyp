import React, { memo, useCallback, useMemo, useState, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { useSelector } from 'react-redux';
import { Card, message } from 'antd';
import { useTranslation } from 'react-i18next';

import { handleProChatRequest, generateWelcomeMessage } from '../utils/proChatHelpers.js';
import { handleProChatRequestWithSse } from '../utils/proChatRequestWithSse.js';
import extractMessageText from '../utils/extractMessageText';
import ChatComposer from './Chat/ChatComposer.jsx';
import ChatMessageList from './Chat/ChatMessageList.jsx';
import {
    appendProgressMessage,
    buildChatRequest,
    CHAT_REQUEST_ERROR_MESSAGE,
    EMPTY_COPY_WARNING,
    getAutofillChatPayload,
    parseChatResponseText,
} from './Chat/chatLogic.js';

function Chat({ widthSize = null }) {
    const { i18n } = useTranslation();
    const { items: documents, selectedFileIds } = useSelector((state) => state.documents);
    const filteredDocuments = useMemo(() => documents, [documents]);

    const [content, setContent] = useState('');
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [enableProgress, setEnableProgress] = useState(true);
    const [progressMessages, setProgressMessages] = useState([]);

    const welcomeMessage = useMemo(() => {
        return generateWelcomeMessage(filteredDocuments.length, selectedFileIds.length);
    }, [filteredDocuments.length, selectedFileIds.length, i18n.language]);

    const handleClearChat = useCallback(() => {
        setMessages([]);
        setContent('');
        setProgressMessages([]);
    }, []);

    const handleCopy = useCallback((messageContent) => {
        const textToCopy = extractMessageText(messageContent);
        if (!textToCopy.trim()) {
            message.warning(EMPTY_COPY_WARNING);
            return;
        }
        navigator.clipboard.writeText(textToCopy)
            .then(() => message.success('Copied to clipboard'))
            .catch(() => message.error('Failed to copy to clipboard'));
    }, []);

    const handleChatRequest = useCallback((userMessage) => {
        if (!userMessage.trim()) return;

        setIsLoading(true);
        setProgressMessages([]);

        const userMessageObj = { id: `user-${Date.now()}`, message: userMessage, status: 'local' };
        const loadingMessageObj = { id: `loading-${Date.now()}`, message: 'Handling your request...', status: 'loading' };

        flushSync(() => {
            setMessages(prev => [...prev, userMessageObj, loadingMessageObj]);
        });

        const { messagesForAPI, requestOptions } = buildChatRequest({
            userMessage,
            selectedFileIds,
            documentCount: filteredDocuments.length,
        });

        const handleSuccess = async (response) => {
            const responseText = await response.text();
            const responseContent = parseChatResponseText(responseText);
            setMessages(prev => [
                ...prev.filter(msg => msg.status !== 'loading'),
                { id: `ai-${Date.now()}`, message: responseContent, status: 'ai' },
            ]);
        };

        const handleError = (error) => {
            console.error('Chat request failed:', error);
            setMessages(prev => [
                ...prev.filter(msg => msg.status !== 'loading'),
                { id: `ai-error-${Date.now()}`, message: CHAT_REQUEST_ERROR_MESSAGE, status: 'ai' },
            ]);
        };

        const apiCall = enableProgress
            ? handleProChatRequestWithSse(messagesForAPI, {
                ...requestOptions,
                onProgress: (progressEvent) => {
                    setProgressMessages(prev => appendProgressMessage(prev, progressEvent));
                },
            })
            : handleProChatRequest(messagesForAPI, requestOptions);

        apiCall.then(handleSuccess).catch(handleError).finally(() => {
            setIsLoading(false);
        });
    }, [selectedFileIds, filteredDocuments, enableProgress]);

    const handleResend = useCallback((messageContent) => {
        const msgToResend = messages.find(msg => msg.message === messageContent && msg.status === 'local');
        if (msgToResend) {
            handleChatRequest(msgToResend.message);
        }
    }, [messages, handleChatRequest]);

    useEffect(() => {
        const handler = (event) => {
            const { text, autoSend, hasText } = getAutofillChatPayload(event);
            if (hasText) {
                setContent(text);
                if (autoSend) {
                    handleChatRequest(text);
                    setContent('');
                }
            }
        };
        window.addEventListener('autofill_chat', handler);
        return () => window.removeEventListener('autofill_chat', handler);
    }, [handleChatRequest]);

    return (
        <Card hoverable className="h-full flex flex-col" style={{ width: widthSize || '100%' }} styles={{ body: { height: '100%', padding: 0, display: 'flex', flexDirection: 'column' } }}>
            <div className="flex flex-col h-full gap-4">
                <div className="flex-1 overflow-y-auto p-4">
                    <ChatMessageList
                        messages={messages}
                        welcomeMessage={welcomeMessage}
                        enableProgress={enableProgress}
                        progressMessages={progressMessages}
                        onCopy={handleCopy}
                        onResend={handleResend}
                    />
                </div>
                <ChatComposer
                    content={content}
                    isLoading={isLoading}
                    hasMessages={messages.length > 0}
                    enableProgress={enableProgress}
                    onChange={setContent}
                    onSubmit={handleChatRequest}
                    onClear={handleClearChat}
                    onProgressChange={setEnableProgress}
                />
            </div>
        </Card>
    );
}

export default memo(Chat);
