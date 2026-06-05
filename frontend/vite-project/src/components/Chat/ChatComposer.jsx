import React from 'react';
import { Button, Space, Spin, Switch, Typography } from 'antd';
import { ClearOutlined } from '@ant-design/icons';
import { Sender } from '@ant-design/x';

export default function ChatComposer({
    content,
    isLoading,
    hasMessages,
    enableProgress,
    onChange,
    onSubmit,
    onClear,
    onProgressChange,
}) {
    return (
        <div className="p-4 border-t border-gray-200">
            <div className="flex gap-2 items-center mb-2">
                <div className="flex items-center gap-2">
                    <Switch size="small" checked={enableProgress} onChange={onProgressChange} />
                    <span className="text-xs text-gray-500">Show Retrieval Progress</span>
                </div>
            </div>
            <div className="flex gap-2 items-center">
                <div className="flex-1">
                    <Sender
                        loading={isLoading}
                        value={content}
                        onChange={onChange}
                        allowSpeech
                        onSubmit={(nextContent) => {
                            onSubmit(nextContent);
                            onChange('');
                        }}
                        placeholder="please enter your question here..."
                        actions={(_, info) => {
                            const { SendButton, LoadingButton, SpeechButton } = info.components;
                            return (
                                <Space size="small">
                                    <Typography.Text type="secondary">
                                        <small>`Enter` to submit</small>
                                    </Typography.Text>
                                    {hasMessages && (
                                        <Button type="text" icon={<ClearOutlined />} onClick={onClear} title="Clear chat" className="flex-shrink-0" />
                                    )}
                                    <SpeechButton />
                                    {isLoading ? (
                                        <LoadingButton type="default" icon={<Spin size="small" />} disabled />
                                    ) : (
                                        <SendButton type="primary" disabled={false} />
                                    )}
                                </Space>
                            );
                        }}
                    />
                </div>
            </div>
        </div>
    );
}
