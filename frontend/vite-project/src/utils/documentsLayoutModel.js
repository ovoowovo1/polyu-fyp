export const COLLAPSED_WIDTH = 60;
export const RESIZER_WIDTH = 12;
export const RESIZER_COUNT = 2;
export const MIN_DOCUMENT_LIST_WIDTH = 280;
export const MIN_STUDIO_CARD_WIDTH = 320;
export const MIN_CHAT_WIDTH = 420;
export const DEFAULT_DOCUMENT_LIST_RATIO = 0.2;
export const DEFAULT_STUDIO_CARD_RATIO = 0.25;
export const LAYOUT_STORAGE_PREFIX = 'documents-page-layout';
export const LEFT_WIDTH_VAR = '--documents-left-width';
export const RIGHT_WIDTH_VAR = '--documents-right-width';
export const CHAT_WIDTH_VAR = '--documents-chat-width';

export function getLayoutStorageKey(classId) {
    return `${LAYOUT_STORAGE_PREFIX}:${classId || 'global'}`;
}

export function getAvailablePanelWidth(containerWidth) {
    const numericWidth = Number.isFinite(containerWidth) ? containerWidth : 0;
    return Math.max(0, numericWidth - (RESIZER_WIDTH * RESIZER_COUNT));
}

export function getMeasuredPanelWidth({
    measuredWidth,
    paddingLeft = 0,
    paddingRight = 0,
}) {
    const numericWidth = Number.isFinite(measuredWidth) ? measuredWidth : 0;
    const left = Number.isFinite(paddingLeft) ? paddingLeft : 0;
    const right = Number.isFinite(paddingRight) ? paddingRight : 0;

    return Math.max(0, numericWidth - left - right);
}

export function getDefaultExpandedWidths(containerWidth) {
    const availableWidth = getAvailablePanelWidth(containerWidth);

    if (availableWidth <= 0) {
        return {
            leftWidth: MIN_DOCUMENT_LIST_WIDTH,
            rightWidth: MIN_STUDIO_CARD_WIDTH,
        };
    }

    const unclampedLeft = Math.round(availableWidth * DEFAULT_DOCUMENT_LIST_RATIO);
    const unclampedRight = Math.round(availableWidth * DEFAULT_STUDIO_CARD_RATIO);
    const maxLeft = Math.max(MIN_DOCUMENT_LIST_WIDTH, availableWidth - MIN_CHAT_WIDTH - MIN_STUDIO_CARD_WIDTH);
    const leftWidth = clamp(unclampedLeft, MIN_DOCUMENT_LIST_WIDTH, maxLeft);
    const maxRight = Math.max(MIN_STUDIO_CARD_WIDTH, availableWidth - MIN_CHAT_WIDTH - leftWidth);
    const rightWidth = clamp(unclampedRight, MIN_STUDIO_CARD_WIDTH, maxRight);

    return { leftWidth, rightWidth };
}

export function clampWidths({
    containerWidth,
    leftWidth,
    rightWidth,
}) {
    const availableWidth = getAvailablePanelWidth(containerWidth);

    if (availableWidth <= 0) {
        return {
            leftWidth: MIN_DOCUMENT_LIST_WIDTH,
            rightWidth: MIN_STUDIO_CARD_WIDTH,
            chatWidth: MIN_CHAT_WIDTH,
        };
    }

    const maxLeft = Math.max(MIN_DOCUMENT_LIST_WIDTH, availableWidth - MIN_CHAT_WIDTH - MIN_STUDIO_CARD_WIDTH);
    const nextLeft = clamp(leftWidth, MIN_DOCUMENT_LIST_WIDTH, maxLeft);
    const maxRight = Math.max(MIN_STUDIO_CARD_WIDTH, availableWidth - MIN_CHAT_WIDTH - nextLeft);
    const nextRight = clamp(rightWidth, MIN_STUDIO_CARD_WIDTH, maxRight);
    const chatWidth = Math.max(MIN_CHAT_WIDTH, availableWidth - nextLeft - nextRight);

    return {
        leftWidth: nextLeft,
        rightWidth: nextRight,
        chatWidth,
    };
}

export function loadSavedExpandedWidths(storage, storageKey) {
    try {
        const raw = storage?.getItem?.(storageKey);
        if (!raw) {
            return null;
        }

        const parsed = JSON.parse(raw);
        if (!Number.isFinite(parsed?.leftWidth) || !Number.isFinite(parsed?.rightWidth)) {
            return null;
        }

        return {
            leftWidth: parsed.leftWidth,
            rightWidth: parsed.rightWidth,
        };
    } catch {
        return null;
    }
}

export function saveExpandedWidths(storage, storageKey, widths) {
    storage?.setItem?.(storageKey, JSON.stringify({
        leftWidth: widths.leftWidth,
        rightWidth: widths.rightWidth,
    }));
}

export function buildLayoutState({
    containerWidth,
    savedWidths,
    isDocumentListCollapsed,
    isStudioCardCollapsed,
}) {
    const fallbackWidths = getDefaultExpandedWidths(containerWidth);
    const expandedWidths = savedWidths || fallbackWidths;
    const clampedExpanded = clampWidths({
        containerWidth,
        leftWidth: expandedWidths.leftWidth,
        rightWidth: expandedWidths.rightWidth,
    });

    const leftWidth = isDocumentListCollapsed ? COLLAPSED_WIDTH : clampedExpanded.leftWidth;
    const rightWidth = isStudioCardCollapsed ? COLLAPSED_WIDTH : clampedExpanded.rightWidth;
    const chatWidth = Math.max(
        MIN_CHAT_WIDTH,
        getAvailablePanelWidth(containerWidth) - leftWidth - rightWidth,
    );

    return {
        documentListWidth: `${leftWidth}px`,
        studioCardWidth: `${rightWidth}px`,
        chatWidth: `${chatWidth}px`,
        expandedLeftWidth: clampedExpanded.leftWidth,
        expandedRightWidth: clampedExpanded.rightWidth,
        chatWidthPx: chatWidth,
    };
}

export function buildDraggedExpandedWidths({
    containerWidth,
    side,
    delta,
    startLeftWidth,
    startRightWidth,
}) {
    const nextWidths = side === 'left'
        ? {
            leftWidth: startLeftWidth + delta,
            rightWidth: startRightWidth,
        }
        : {
            leftWidth: startLeftWidth,
            rightWidth: startRightWidth - delta,
        };

    return clampWidths({
        containerWidth,
        leftWidth: nextWidths.leftWidth,
        rightWidth: nextWidths.rightWidth,
    });
}

export function getLayoutCssVariables(layout) {
    return {
        [LEFT_WIDTH_VAR]: layout.documentListWidth,
        [RIGHT_WIDTH_VAR]: layout.studioCardWidth,
        [CHAT_WIDTH_VAR]: layout.chatWidth,
    };
}

function clamp(value, min, max) {
    if (!Number.isFinite(value)) {
        return min;
    }

    return Math.min(Math.max(value, min), max);
}
