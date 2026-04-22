import React from 'react';

import axios from 'axios';
import MarkdownIt from 'markdown-it';

import { API_BASE_URL } from '../config.js';
import Citation from '../components/Citation.jsx';
import i18n from '../i18n/config.js';


// 初始化 markdown-it，並啟用 HTML 解析
const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
});

export const handleProChatRenderConfig = {
    contentRender: (props, defaultDom) => {
        if (props.originData?.role === 'assistant' && typeof props.originData?.content === 'string') {
            try {
                const contentParts = JSON.parse(props.originData.content);

                if (Array.isArray(contentParts)) {
                    return (
                        <div className="prose max-w-none markdown-content leading-relaxed text-sm">
                            {contentParts.map((part, index) => {
                                if (part.type === 'text') {
                                    // 使用 render() 來處理標題等區塊語法
                                    let renderedHtml = md.render(part.value);

                                    // 移除外層的 <p> 標籤以避免不必要的換行
                                    if (renderedHtml.startsWith('<p>') && renderedHtml.endsWith('</p>\n')) {
                                        // 確保只在只有一個段落時才移除 p 標籤，以保留多段落的格式
                                        const pCount = (renderedHtml.match(/<p>/g) || []).length;
                                        if (pCount === 1) {
                                            renderedHtml = renderedHtml.slice(3, renderedHtml.length - 5); // 移除 <p> 和 </p>\n
                                        }
                                    }

                                    return <span key={index} dangerouslySetInnerHTML={{ __html: renderedHtml }} />;
                                }
                                if (part.type === 'citation') {
                                    return (
                                        <Citation part={part} index={index} />
                                    );
                                }
                                return null;
                            })}
                        </div>
                    );
                }
            } catch (e) {
                // 如果解析失敗，則回退到預設渲染
                const content = props.originData.content;
                const renderedContent = md.render(content);
                return (
                    <div
                        dangerouslySetInnerHTML={{ __html: renderedContent }}
                        className="prose max-w-none markdown-content  leading-relaxed text-sm"
                    />
                );
            }
        }
        // 其他情況使用預設的 Markdown 渲染
        return defaultDom;
    }
};






/**
 * 支援進度回饋的 ProChat API 請求處理器
 * @param {Array} messages - ProChat 傳遞的訊息陣列
 * @param {Object} options - 可選配置
 * @returns {Response} - 返回標準的 Response 對象
 */
export const handleProChatRequestWithProgress = async (messages, options = {}) => {
    const { requestBody = {}, onProgress } = options;

    try {
        const lastMessage = messages[messages.length - 1];
        const userQuestion = lastMessage?.content;

        if (!userQuestion) {
            throw new Error('無效的訊息內容');
        }

        console.log('ProChat SSE 發送查詢:', userQuestion);
        console.log('請求 URL:', `${API_BASE_URL}/api/query-stream`);

        const requestData = {
            question: userQuestion,
            ...requestBody
        };

        if (requestBody?.selectedFileIds && requestBody.selectedFileIds.length > 0) {
            console.log('查詢限制在選中的文件:', requestBody.selectedFileIds);
        }

        console.log('發送 SSE 請求:', requestData);

        const response = await fetch(`${API_BASE_URL}/api/query-stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestData),
        });

        console.log('SSE 響應狀態:', response.status);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let finalResult = null;
        let buffer = '';

        console.log('開始讀取 SSE 流...');

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    console.log('SSE 流讀取完成');
                    break;
                }

                const chunk = decoder.decode(value, { stream: true });
                console.log('收到 SSE 數據塊:', chunk);
                buffer += chunk;
                const parts = buffer.split('\n');
                // 將最後一段暫存（可能是未完整的 JSON）
                buffer = parts.pop() || '';

                for (const rawLine of parts) {
                    const line = rawLine.trim();
                    if (!line) continue;
                    try {
                        const data = JSON.parse(line);
                        console.log('解析到 SSE 數據:', data);

                        if (onProgress && data.type !== 'result') {
                            onProgress(data);
                        }

                        if (data.type === 'result') {
                            console.log('收到最終結果:', data);
                            finalResult = data;
                        }
                    } catch (e) {
                        console.warn('解析 SSE 數據失敗:', e, '原始數據:', line);
                    }
                }
            }
        } finally {
            reader.releaseLock();
        }

        // 嘗試解析可能殘留在緩衝區的最後一條訊息
        const last = (buffer || '').trim();
        if (last) {
            try {
                const data = JSON.parse(last);
                if (onProgress && data.type !== 'result') {
                    onProgress(data);
                }
                if (data.type === 'result') {
                    finalResult = data;
                }
            } catch (e) {
                console.warn('解析 SSE 殘留數據失敗:', e, '原始數據:', last);
            }
        }

        // 處理最終結果，轉換為結構化內容
        if (finalResult) {
            const answer_with_citations = finalResult.answer_with_citations;
            const structuredContent = [];
            const rawSources = Array.isArray(finalResult.raw_sources) ? finalResult.raw_sources : [];
            const sourceByChunkId = new Map(rawSources.map(s => [String(s.chunkId), s]));

            if (!answer_with_citations || answer_with_citations.length === 0) {
                structuredContent.push({ type: 'text', value: finalResult.answer || '抱歉，我無法處理您的請求' });
            } else {
                const citationRefs = new Map();
                let citationCounter = 1;

                for (const segment of answer_with_citations) {
                    if (segment.content_segments && segment.content_segments.length > 0) {
                        let accumulatedText = '';

                        for (let i = 0; i < segment.content_segments.length; i++) {
                            const currentSubSegment = segment.content_segments[i];
                            const nextSubSegment = segment.content_segments[i + 1];

                            accumulatedText += currentSubSegment.segment_text + '\n';

                            // 支持新的 source_references 数组格式（向后兼容 source_reference）
                            const sourceRefs = currentSubSegment.source_references || 
                                              (currentSubSegment.source_reference ? [currentSubSegment.source_reference] : []);
                            
                            const nextSourceRefs = nextSubSegment?.source_references || 
                                                  (nextSubSegment?.source_reference ? [nextSubSegment.source_reference] : []);

                            // 比较当前和下一个段落的来源是否相同
                            const sourcesChanged = !nextSubSegment || 
                                JSON.stringify(sourceRefs.map(s => s.file_chunk_id).sort()) !== 
                                JSON.stringify(nextSourceRefs.map(s => s.file_chunk_id).sort());

                            if (sourcesChanged) {
                                structuredContent.push({ type: 'text', value: accumulatedText.trim() });
                                accumulatedText = '';

                                // 为每个来源创建引用标记
                                sourceRefs.forEach(sourceRef => {
                                    const citationId = sourceRef.file_chunk_id;
                                    let citationNumber;

                                    if (citationRefs.has(citationId)) {
                                        citationNumber = citationRefs.get(citationId);
                                    } else {
                                        citationNumber = citationCounter;
                                        citationRefs.set(citationId, citationNumber);
                                        citationCounter++;
                                    }

                                    const sourceEntry = sourceByChunkId.get(String(citationId));

                                    structuredContent.push({
                                        type: 'citation',
                                        number: citationNumber,
                                        details: {
                                            fileId: sourceEntry?.fileId,
                                            chunkId: citationId,
                                            source: sourceEntry?.source,
                                            page: sourceEntry?.pageNumber,
                                        }
                                    });
                                });
                            }
                        }
                    }
                }
            }

            return {
                text: () => Promise.resolve(JSON.stringify(structuredContent))
            };
        }

        throw new Error('未收到有效的結果');

    } catch (error) {
        console.error('ProChat SSE 請求錯誤:', error);
        let errorMessage = 'Sorry, something went wrong. Please try again later.';
        if (error.response?.status === 503) {
            errorMessage = 'Service temporarily unavailable, please try again later.';
        } else if (error.response?.status === 400) {
            errorMessage = error.response.data?.error || 'Request format error.';
        } else if (error.code === 'NETWORK_ERROR') {
            errorMessage = 'Network connection error, please check your network settings.';
        }
        return {
            text: () => Promise.resolve(errorMessage)
        };
    }
};

/**
 * 標準的 ProChat API 請求處理器（向後兼容）
 * @param {Array} messages - ProChat 傳遞的訊息陣列
 * @param {Object} options - 可選配置
 * @returns {Response} - 返回標準的 Response 對象
 */
export const handleProChatRequest = async (messages, options = {}) => {
    try {
        const lastMessage = messages[messages.length - 1];
        const userQuestion = lastMessage?.content;

        if (!userQuestion) {
            throw new Error('無效的訊息內容');
        }

        console.log('ProChat 發送查詢:', userQuestion);

        const requestBody = {
            question: userQuestion,
            ...options.requestBody
        };

        if (options.requestBody?.selectedFileIds && options.requestBody.selectedFileIds.length > 0) {
            console.log('查詢限制在選中的文件:', options.requestBody.selectedFileIds);
        }

        const response = await axios.post(`${API_BASE_URL}/query`, requestBody);

        const answer_with_citations = response.data.answer_with_citations;
        const structuredContent = [];

        if (!answer_with_citations || answer_with_citations.length === 0) {
            structuredContent.push({ type: 'text', value: response.data.answer || '抱歉，我無法處理您的請求' });
        } else {
            const citationRefs = new Map();
            let citationCounter = 1;

            // 遍歷所有主要的回答區塊 (通常只有一個)
            for (const segment of answer_with_citations) {
                if (segment.content_segments && segment.content_segments.length > 0) {

                    let accumulatedText = ''; // 用於合併來自同一個來源的連續文本

                    // 遍歷所有文字子片段
                    for (let i = 0; i < segment.content_segments.length; i++) {
                        const currentSubSegment = segment.content_segments[i];
                        const nextSubSegment = segment.content_segments[i + 1];

                        // 將當前文字片段的文字累加起來。
                        // 使用 '\n' 確保每個原始片段都能換行，最終由 markdown 渲染器處理格式。
                        accumulatedText += currentSubSegment.segment_text + '\n';

                        // 支持新的 source_references 数组格式（向后兼容 source_reference）
                        const sourceRefs = currentSubSegment.source_references || 
                                          (currentSubSegment.source_reference ? [currentSubSegment.source_reference] : []);
                        
                        const nextSourceRefs = nextSubSegment?.source_references || 
                                              (nextSubSegment?.source_reference ? [nextSubSegment.source_reference] : []);

                        // 判斷是否需要插入引用：比较当前和下一个段落的来源是否相同
                        const sourcesChanged = !nextSubSegment || 
                            JSON.stringify(sourceRefs.map(s => s.file_chunk_id).sort()) !== 
                            JSON.stringify(nextSourceRefs.map(s => s.file_chunk_id).sort());

                        if (sourcesChanged) {
                            // 將合併好的文字推入結構化內容中
                            structuredContent.push({ type: 'text', value: accumulatedText.trim() });
                            // 重置文字累加器，為下一個不同的來源做準備
                            accumulatedText = '';

                            // 為每個來源創建引用標記
                            sourceRefs.forEach(sourceRef => {
                                const citationId = sourceRef.file_chunk_id;
                                let citationNumber;

                                if (citationRefs.has(citationId)) {
                                    citationNumber = citationRefs.get(citationId);
                                } else {
                                    citationNumber = citationCounter;
                                    citationRefs.set(citationId, citationNumber);
                                    citationCounter++;
                                }

                                // 將引用物件推入結構化內容中
                                structuredContent.push({
                                    type: 'citation',
                                    number: citationNumber,
                                    details: {
                                        fileId: sourceRef.file_id,
                                        chunkId: citationId,
                                        source: sourceRef.source_file,
                                        page: sourceRef.page_number,
                                    }
                                });
                            });
                        }
                    }
                }
            }
        }

        return new Response(JSON.stringify(structuredContent), {
            headers: { 'Content-Type': 'application/json' }
        });

    } catch (error) {
        console.error('ProChat API 請求錯誤:', error);
        let errorMessage = '抱歉，發生了錯誤，請稍後再試。';
        if (error.response?.status === 503) {
            errorMessage = '服務暫時不可用，請稍後再試。';
        } else if (error.response?.status === 400) {
            errorMessage = error.response.data?.error || '請求格式錯誤。';
        } else if (error.code === 'NETWORK_ERROR') {
            errorMessage = '網路連接錯誤，請檢查網路設定。';
        }
        return new Response(errorMessage, {
            status: error.response?.status || 500,
            headers: { 'Content-Type': 'text/plain' }
        });
    }
};

/**
 * 創建串流回應的處理器（進階功能）
 * @param {Array} messages - ProChat 傳遞的訊息陣列
 * @returns {Response} - 返回串流 Response 對象
 */
export const handleStreamingRequest = async (messages) => {
    try {
        const lastMessage = messages[messages.length - 1];
        const userQuestion = lastMessage?.content;

        if (!userQuestion) {
            throw new Error('無效的訊息內容');
        }

        // 創建一個可讀流
        const stream = new ReadableStream({
            async start(controller) {
                try {
                    // 模擬分段回應
                    const response = await axios.post(`${API_BASE_URL}/query`, {
                        question: userQuestion
                    });

                    const answer = response.data.answer || 'Sorry, I could not process your request.';

                    // 將回應分成小段進行串流
                    const words = answer.split(' ');
                    for (let i = 0; i < words.length; i++) {
                        const chunk = words[i] + (i < words.length - 1 ? ' ' : '');
                        controller.enqueue(new TextEncoder().encode(chunk));

                        // 添加小延遲以模擬串流效果
                        await new Promise(resolve => setTimeout(resolve, 50));
                    }

                    controller.close();
                } catch (error) {
                    controller.error(error);
                }
            }
        });

        return new Response(stream, {
            headers: {
                'Content-Type': 'text/plain',
                'Transfer-Encoding': 'chunked'
            }
        });

    } catch (error) {
        console.error('串流請求錯誤:', error);
        return new Response('串流請求失敗', {
            status: 500,
            headers: { 'Content-Type': 'text/plain' }
        });
    }
};

/**
 * ProChat 配置預設值
 */
export const defaultProChatConfig = {
    placeholder: "Ask me anything about your uploaded documents...",
    helloMessage: "Welcome to the Smart Document Assistant! I can help you analyze and query the content of your uploaded documents.",
    style: {
        padding: '1rem',
        height: '100%'
    },
    // 自定義主題配色
    theme: {
        token: {
            colorPrimary: '#1890ff',
            borderRadius: 8,
        }
    }
};

/**
 * 根據文件數量和選中數量生成動態歡迎訊息
 * @param {number} documentCount - 總文件數量
 * @param {number} selectedCount - 選中的文件數量
 * @returns {string} - 歡迎訊息
 */
export const generateWelcomeMessage = (documentCount, selectedCount = 0) => {
    if (documentCount === 0) {
        return i18n.t('chat.welcomeNoDocuments');
    }

    let baseMessage = i18n.t('chat.welcomeWithDocuments', { count: documentCount });

    if (selectedCount > 0 && selectedCount < documentCount) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedPartial', { count: selectedCount })}`;
    } else if (selectedCount === documentCount && documentCount > 1) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedAll')}`;
    } else {
        baseMessage += `\n\n${i18n.t('chat.welcomeNoSelection')}`;
    }

    baseMessage += `\n\n${i18n.t('chat.welcomeAskQuestions')}`;

    return baseMessage;
};
