import React, { memo, useCallback, useMemo, useState, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { useSelector } from 'react-redux';
import { Card, Button, Spin, message, Switch, Tooltip, Space, Typography } from 'antd';
import { UserOutlined, ReloadOutlined, CopyOutlined, ClearOutlined   } from '@ant-design/icons';
import { Bubble, Sender } from '@ant-design/x';
import MarkdownIt from 'markdown-it';
import { useTranslation } from 'react-i18next';

import { handleProChatRequest, generateWelcomeMessage } from '../utils/proChatHelpers.jsx';
import { handleProChatRequestWithSse } from '../utils/proChatRequestWithSse.js';
import Citation from '../components/Citation.jsx';
import TTSButton from '../components/TTSButton.jsx';
import AdaptiveRetrievalProgress from '../components/AdaptiveRetrievalProgress.jsx';
import extractMessageText from '../utils/extractMessageText';




const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
});

const renderMessageContent = (content) => {
    if (typeof content === 'string') {
        const renderedContent = md.render(content);
        return <div dangerouslySetInnerHTML={{ __html: renderedContent }} className="prose max-w-none markdown-content leading-relaxed text-sm" />;
    }
    if (Array.isArray(content)) {
        return (
            <div className="prose max-w-none markdown-content leading-relaxed text-sm">
                {content.map((part, index) => {
                    if (part.type === 'text') {
                        let renderedHtml = md.render(part.value);
                        if (renderedHtml.startsWith('<p>') && renderedHtml.endsWith('</p>\n') && (renderedHtml.match(/<p>/g) || []).length === 1) {
                            renderedHtml = renderedHtml.slice(3, renderedHtml.length - 5);
                        }
                        return <span key={index} dangerouslySetInnerHTML={{ __html: renderedHtml }} />;
                    }
                    if (part.type === 'citation') {
                        return <Citation key={index} part={part} index={index} />;
                    }
                    return null;
                })}
            </div>
        );
    }
    return <div>{String(content)}</div>;
};

function Chat({ widthSize = null }) {
    const { i18n } = useTranslation();
    const { items: documents, selectedFileIds } = useSelector((state) => state.documents);
    const filteredDocuments = useMemo(() => documents, [documents]);

    const [content, setContent] = useState('');
    const [messages, setMessages] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [enableProgress, setEnableProgress] = useState(true);
    const [progressMessages, setProgressMessages] = useState([]);

    // 當語言變化時重新計算歡迎訊息
    const welcomeMessage = useMemo(() => {
        return generateWelcomeMessage(filteredDocuments.length, selectedFileIds.length);
    }, [filteredDocuments.length, selectedFileIds.length, i18n.language]);




    const handleClearChat = useCallback(() => {
        setMessages([]);
        setContent('');
        setProgressMessages([]);
    }, []);

    const handleCopy = useCallback((messageContent) => {
        console.log('handleCopy called with:', typeof messageContent, messageContent);
        const textToCopy = extractMessageText(messageContent);
        console.log('Copying text:', textToCopy);
        if (!textToCopy.trim()) {
            message.warning('沒有可複製的內容');
            return;
        }
        navigator.clipboard.writeText(textToCopy)
            .then(() => message.success('Copied to clipboard'))
            .catch(() => message.error('Failed to copy to clipboard'));
    }, []);

    const handleResend = useCallback((messageContent) => {
        const msgToResend = messages.find(msg => msg.message === messageContent && msg.status === 'local');
        if (msgToResend) {
            handleChatRequest(msgToResend.message);
        }
    }, [messages]);

    const roles = useMemo(() => ({
        ai: {
            placement: 'start',
            avatar: { icon: <UserOutlined />, style: { background: '#fde3cf' } },
            style: { width: '80%' },
        },
        local: {
            placement: 'end',
            avatar: { icon: <UserOutlined />, style: { background: '#87d068' } },
        },
    }), []);

    const handleChatRequest = useCallback((userMessage) => {
        if (!userMessage.trim()) return;

        setIsLoading(true);
        setProgressMessages([]);

        const userMessageObj = { id: `user-${Date.now()}`, message: userMessage, status: 'local' };
        const loadingMessageObj = { id: `loading-${Date.now()}`, message: 'Handling your request...', status: 'loading' };

        flushSync(() => {
            setMessages(prev => [...prev, userMessageObj, loadingMessageObj]);
        });

        const messagesForAPI = [{ content: userMessage }];
        const requestOptions = {
            requestBody: {
                selectedFileIds: selectedFileIds.length > 0 ? selectedFileIds : undefined,
                documentCount: filteredDocuments.length,
                selectedCount: selectedFileIds.length,
            },
        };

        const handleSuccess = async (response) => {
            const responseText = await response.text();
            let responseContent;
            try { responseContent = JSON.parse(responseText); } catch (e) { responseContent = responseText; }
            setMessages(prev => [
                ...prev.filter(msg => msg.status !== 'loading'),
                { id: `ai-${Date.now()}`, message: responseContent, status: 'ai' },
            ]);
        };

        const handleError = (error) => {
            console.error('聊天請求錯誤:', error);
            setMessages(prev => [
                ...prev.filter(msg => msg.status !== 'loading'),
                { id: `ai-error-${Date.now()}`, message: 'Sorry, something went wrong. Please try again later.', status: 'ai' },
            ]);
        };

        const apiCall = enableProgress
            ? handleProChatRequestWithSse(messagesForAPI, {
                ...requestOptions,
                onProgress: (progressEvent) => {
                    setProgressMessages(prev => [...prev, progressEvent]);
                },
            })
            : handleProChatRequest(messagesForAPI, requestOptions);

        apiCall.then(handleSuccess).catch(handleError).finally(() => {
            setIsLoading(false);
        });

    }, [selectedFileIds, filteredDocuments, enableProgress, messages]);

    // 監聽來自 QuizReader 的 autofill_chat 事件，將文字填回 Sender 的輸入欄
    // 放在 handleChatRequest 之後，確保引用到的 handler 已初始化
    useEffect(() => {
        const handler = (e) => {
            const txt = e?.detail?.text || ''
            const autoSend = !!e?.detail?.send
            if (typeof txt === 'string' && txt.trim()) {
                setContent(txt)
                if (autoSend) {
                    // 呼叫聊天請求並清空輸入欄
                    handleChatRequest(txt)
                    setContent('')
                }
            }
        }
        window.addEventListener('autofill_chat', handler)
        return () => window.removeEventListener('autofill_chat', handler)
    }, [handleChatRequest])

    return (
        <Card hoverable className="h-full flex flex-col" style={{ width: widthSize || '100%' }} styles={{ body: { height: '100%', padding: 0, display: 'flex', flexDirection: 'column' } }}>
            <div className="flex flex-col h-full gap-4">
                <div className="flex-1 overflow-y-auto p-4">
                    {messages.length === 0 ? (
                        <Bubble content={welcomeMessage} placement="start" variant="outlined" avatar={{ icon: <UserOutlined />, style: { background: '#fde3cf' } }} />
                    ) : (
                        <Bubble.List
                            roles={roles}
                            items={messages.map(({ id, message, status }, index) => {
   
                                let finalContent;

                                if (status === 'loading' && enableProgress) {
      
                                    finalContent = (
                                            <div className='w-full'>
                                            <AdaptiveRetrievalProgress progressMessages={progressMessages} />
                                            <div className="flex items-center gap-2 mt-2">
                                                <Spin size="small" />
                                                <span>{message}</span>
                                            </div>
                                        </div>
                                    );
                                } else if (status === 'ai') {
                                    const isLastMessage = index === messages.length - 1;

                                    if (isLastMessage && enableProgress && progressMessages.length > 0) {
                                        finalContent = (
                                            <div className='w-full'>
                                                <AdaptiveRetrievalProgress progressMessages={progressMessages} />
                                                {renderMessageContent(message)}
                                            </div>
                                        );
                                    } else {
                                        finalContent = renderMessageContent(message);
                                    }
                                } else { 
                                    finalContent = message;
                                }

                                return {
                                    variant: "outlined",
                                    key: id,
                                   
                                    styles: {
                                        content: { width: status === 'local' ? '' : '100%' }
                                    },
                               
                                    footer: status === 'loading' ? null : (
                                        status === 'local' ? (
                                            <div className='flex gap-2'>
                                                <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => handleResend(message)} title="重新發送" />
                                                <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => handleCopy(message)} title="複製訊息" />
                                            </div>
                                        ) : (
                                            <div className='flex gap-2'>
                                                <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => handleCopy(message)} title="複製回應" />
                                                <TTSButton text={message} />
                                            </div>
                                        )
                                    ),
                                      // 我們不再傳遞 loading: true，而是自己控制內容
                                    role: status === 'local' ? 'local' : 'ai',
                                    content: finalContent,
                                    'data-original-message': JSON.stringify(message),
                                };
                            })}
                        />
                    )}
                </div>
                <div className="p-4 border-t border-gray-200">
                    <div className="flex gap-2 items-center mb-2">
                            <div className="flex items-center gap-2">
                                <Switch size="small" checked={enableProgress} onChange={setEnableProgress} />
                                <span className="text-xs text-gray-500">Show Retrieval Progress</span>
                            </div>
                    </div>
                    <div className="flex gap-2 items-center">
                        <div className="flex-1">
                            <Sender

                                loading={isLoading}
                                value={content}
                                onChange={setContent}
                                allowSpeech
                                onSubmit={nextContent => { handleChatRequest(nextContent); setContent(''); }}
                                placeholder='please enter your question here...'
                                actions={(_, info) => {
                                    const { SendButton, LoadingButton, ClearButton, SpeechButton } = info.components;
                                    return (
                                        <>
                                            <Space size="small">
                                                <Typography.Text type="secondary">
                                                    <small>`Enter` to submit</small>
                                                </Typography.Text>
                                                { messages.length > 0 && <Button type="text" icon={<ClearOutlined />} onClick={handleClearChat} title="清空對話" className="flex-shrink-0" /> }
                                                <SpeechButton />
                                                {isLoading ? (
                                                    <LoadingButton type="default" icon={<Spin size="small" />} disabled />
                                                ) : (
                                                    <SendButton type="primary" disabled={false} />
                                                )}
                                            </Space>

                                        </>
                                    )
                                }}

                            />
                        </div>

                    </div>
                </div>
            </div>
        </Card>
    );
}

export default memo(Chat);
