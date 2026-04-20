import { useMemo } from 'react';

// 定義寬度常量
const WIDTHS = {
    COLLAPSED: '60px',
    DOCUMENT_LIST: {
        NORMAL: '20%',
        EXPANDED: '25%',
    },
    STUDIO_CARD: {
        NORMAL: '25%',
        QUIZ_READER: '45%',
    },
};

// 定義佈局配置
const LAYOUT_CONFIG = {
    // Key 格式: `docList_${狀態}_studio_${狀態}_quiz_${狀態}`
    
    // DocumentList 正常狀態
    'normal_normal_closed': {
        documentList: WIDTHS.DOCUMENT_LIST.NORMAL,
        chat: '55%',
        studioCard: WIDTHS.STUDIO_CARD.NORMAL,
    },
    'normal_normal_open': {
        documentList: WIDTHS.DOCUMENT_LIST.NORMAL,
        chat: '35%',
        studioCard: WIDTHS.STUDIO_CARD.QUIZ_READER,
    },
    
    // DocumentList 展開內容
    'expanded_normal_closed': {
        documentList: WIDTHS.DOCUMENT_LIST.EXPANDED,
        chat: '50%',
        studioCard: WIDTHS.STUDIO_CARD.NORMAL,
    },
    'expanded_normal_open': {
        documentList: WIDTHS.DOCUMENT_LIST.EXPANDED,
        chat: '30%',
        studioCard: WIDTHS.STUDIO_CARD.QUIZ_READER,
    },
    
    // DocumentList 折疊
    'collapsed_normal_closed': {
        documentList: WIDTHS.COLLAPSED,
        chat: 'calc(75% - 60px)',
        studioCard: WIDTHS.STUDIO_CARD.NORMAL,
    },
    'collapsed_normal_open': {
        documentList: WIDTHS.COLLAPSED,
        chat: 'calc(55% - 60px)',
        studioCard: WIDTHS.STUDIO_CARD.QUIZ_READER,
    },
    
    // StudioCard 折疊
    'normal_collapsed_closed': {
        documentList: WIDTHS.DOCUMENT_LIST.NORMAL,
        chat: 'calc(80% - 60px)',
        studioCard: WIDTHS.COLLAPSED,
    },
    'expanded_collapsed_closed': {
        documentList: WIDTHS.DOCUMENT_LIST.EXPANDED,
        chat: 'calc(75% - 60px)',
        studioCard: WIDTHS.COLLAPSED,
    },
    
    // 兩邊都折疊
    'collapsed_collapsed_closed': {
        documentList: WIDTHS.COLLAPSED,
        chat: 'calc(100% - 120px)',
        studioCard: WIDTHS.COLLAPSED,
    },
};

/**
 * 自定義 Hook 用於計算佈局寬度
 * @param {Object} options
 * @param {boolean} options.isDocumentListCollapsed - DocumentList 是否折疊
 * @param {boolean} options.isStudioCardCollapsed - StudioCard 是否折疊
 * @param {boolean} options.isQuizReaderOpen - QuizReader 是否打開
 * @param {any} options.selectedShowDocumentContentID - 選中的文檔 ID
 * @returns {Object} 包含 documentListWidth, chatWidth, studioCardWidth 的對象
 */
export default function useLayoutWidth({
    isDocumentListCollapsed,
    isStudioCardCollapsed,
    isQuizReaderOpen,
    selectedShowDocumentContentID,
}) {
    return useMemo(() => {
        // 確定 DocumentList 狀態
        const docListState = isDocumentListCollapsed 
            ? 'collapsed' 
            : selectedShowDocumentContentID != null 
                ? 'expanded' 
                : 'normal';
        
        // 確定 StudioCard 狀態
        const studioState = isStudioCardCollapsed ? 'collapsed' : 'normal';
        
        // 確定 QuizReader 狀態
        const quizState = isQuizReaderOpen ? 'open' : 'closed';
        
        // 生成配置 key
        const configKey = `${docListState}_${studioState}_${quizState}`;
        
        // 獲取配置，如果找不到則使用默認配置
        const config = LAYOUT_CONFIG[configKey] || LAYOUT_CONFIG['normal_normal_closed'];
        
        return {
            documentListWidth: config.documentList,
            chatWidth: config.chat,
            studioCardWidth: config.studioCard,
        };
    }, [isDocumentListCollapsed, isStudioCardCollapsed, isQuizReaderOpen, selectedShowDocumentContentID]);
}

