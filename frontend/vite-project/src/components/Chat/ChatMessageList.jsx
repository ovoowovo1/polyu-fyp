import React, { useMemo } from 'react';
import { Button, Spin } from 'antd';
import { CopyOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons';
import { Bubble } from '@ant-design/x';

import AdaptiveRetrievalProgress from '../AdaptiveRetrievalProgress.jsx';
import TTSButton from '../TTSButton.jsx';
import ChatMessageContent from './ChatMessageContent.jsx';

function LoadingProgress({ message, progressMessages }) {
    return (
        <div className="w-full">
            <AdaptiveRetrievalProgress progressMessages={progressMessages} />
            <div className="flex items-center gap-2 mt-2">
                <Spin size="small" />
                <span>{message}</span>
            </div>
        </div>
    );
}

function AiMessageContent({ message, showProgress, progressMessages }) {
    if (!showProgress) {
        return <ChatMessageContent content={message} />;
    }

    return (
        <div className="w-full">
            <AdaptiveRetrievalProgress progressMessages={progressMessages} />
            <ChatMessageContent content={message} />
        </div>
    );
}

function MessageFooter({ status, message, onCopy, onResend }) {
    if (status === 'loading') return null;

    if (status === 'local') {
        return (
            <div className="flex gap-2">
                <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => onResend(message)} title="Resend message" />
                <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => onCopy(message)} title="Copy message" />
            </div>
        );
    }

    return (
        <div className="flex gap-2">
            <Button type="text" size="small" icon={<CopyOutlined />} onClick={() => onCopy(message)} title="Copy answer" />
            <TTSButton text={message} />
        </div>
    );
}

export default function ChatMessageList({
    messages,
    welcomeMessage,
    enableProgress,
    progressMessages,
    onCopy,
    onResend,
}) {
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

    if (messages.length === 0) {
        return (
            <Bubble
                content={welcomeMessage}
                placement="start"
                variant="outlined"
                avatar={{ icon: <UserOutlined />, style: { background: '#fde3cf' } }}
            />
        );
    }

    return (
        <Bubble.List
            roles={roles}
            items={messages.map(({ id, message, status }, index) => {
                const isLastMessage = index === messages.length - 1;
                const showAiProgress = status === 'ai' && isLastMessage && enableProgress && progressMessages.length > 0;
                const content = status === 'loading' && enableProgress
                    ? <LoadingProgress message={message} progressMessages={progressMessages} />
                    : status === 'ai'
                        ? <AiMessageContent message={message} showProgress={showAiProgress} progressMessages={progressMessages} />
                        : message;

                return {
                    variant: 'outlined',
                    key: id,
                    styles: {
                        content: { width: status === 'local' ? '' : '100%' },
                    },
                    footer: <MessageFooter status={status} message={message} onCopy={onCopy} onResend={onResend} />,
                    role: status === 'local' ? 'local' : 'ai',
                    content,
                    'data-original-message': JSON.stringify(message),
                };
            })}
        />
    );
}
