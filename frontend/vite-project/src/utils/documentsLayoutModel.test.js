import test from 'node:test';
import assert from 'node:assert/strict';

import {
    COLLAPSED_WIDTH,
    CHAT_WIDTH_VAR,
    DESKTOP_PAGE_CLASS,
    LEFT_WIDTH_VAR,
    MIN_CHAT_WIDTH,
    MIN_DOCUMENT_LIST_WIDTH,
    MIN_STUDIO_CARD_WIDTH,
    RESIZER_COUNT,
    RESIZER_WIDTH,
    RIGHT_WIDTH_VAR,
    buildLayoutState,
    buildDraggedExpandedWidths,
    clampWidths,
    getDefaultExpandedWidths,
    getLayoutCssVariables,
    getLayoutStorageKey,
    getMeasuredPanelWidth,
    getDesktopLayoutClassName,
    getPanelShellStyle,
    loadSavedExpandedWidths,
    saveExpandedWidths,
} from './documentsLayoutModel.js';

test('uses default desktop widths when no saved widths exist', () => {
    const layout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: null,
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(layout.documentListWidth, '315px');
    assert.equal(layout.studioCardWidth, '394px');
    assert.equal(layout.chatWidth, '867px');
});

test('panel widths plus resize handles fill the measured content width', () => {
    const layout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: null,
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(
        toPixels(layout.documentListWidth)
            + toPixels(layout.chatWidth)
            + toPixels(layout.studioCardWidth)
            + (RESIZER_WIDTH * RESIZER_COUNT),
        1600,
    );
});

test('restores saved widths from storage', () => {
    const storage = createStorage();
    const key = getLayoutStorageKey('class-a');
    saveExpandedWidths(storage, key, { leftWidth: 340, rightWidth: 410 });

    assert.deepEqual(loadSavedExpandedWidths(storage, key), {
        leftWidth: 340,
        rightWidth: 410,
    });
});

test('collapsed panels use the fixed collapsed width', () => {
    const layout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: { leftWidth: 360, rightWidth: 420 },
        isDocumentListCollapsed: true,
        isStudioCardCollapsed: true,
    });

    assert.equal(layout.documentListWidth, `${COLLAPSED_WIDTH}px`);
    assert.equal(layout.studioCardWidth, `${COLLAPSED_WIDTH}px`);
    assert.equal(layout.chatWidth, '1456px');
});

test('expanded panels return to saved widths after collapse state changes', () => {
    const collapsedLayout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: { leftWidth: 360, rightWidth: 420 },
        isDocumentListCollapsed: true,
        isStudioCardCollapsed: false,
    });
    const expandedLayout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: { leftWidth: 360, rightWidth: 420 },
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(collapsedLayout.documentListWidth, `${COLLAPSED_WIDTH}px`);
    assert.equal(expandedLayout.documentListWidth, '360px');
    assert.equal(expandedLayout.studioCardWidth, '420px');
});

test('clampWidths preserves the chat minimum width', () => {
    const clamped = clampWidths({
        containerWidth: 1200,
        leftWidth: 500,
        rightWidth: 500,
    });

    assert.equal(clamped.leftWidth, 436);
    assert.equal(clamped.rightWidth, MIN_STUDIO_CARD_WIDTH);
    assert.equal(clamped.chatWidth, MIN_CHAT_WIDTH);
});

test('default expanded widths honor minimum panel widths on narrow containers', () => {
    const widths = getDefaultExpandedWidths(1100);

    assert.equal(widths.leftWidth, MIN_DOCUMENT_LIST_WIDTH);
    assert.equal(widths.rightWidth, MIN_STUDIO_CARD_WIDTH);
});

test('getMeasuredPanelWidth excludes horizontal padding from available panel width', () => {
    const measured = getMeasuredPanelWidth({
        measuredWidth: 1200,
        paddingLeft: 16,
        paddingRight: 16,
    });

    assert.equal(measured, 1168);
});

test('layout uses measured width after preserving the 16px page gutter', () => {
    const contentWidth = getMeasuredPanelWidth({
        measuredWidth: 1440,
        paddingLeft: 16,
        paddingRight: 16,
    });
    const layout = buildLayoutState({
        containerWidth: contentWidth,
        savedWidths: null,
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(contentWidth, 1408);
    assert.equal(
        toPixels(layout.documentListWidth)
            + toPixels(layout.chatWidth)
            + toPixels(layout.studioCardWidth)
            + (RESIZER_WIDTH * RESIZER_COUNT),
        contentWidth,
    );
});

test('saved widths that are too large clamp to the content width', () => {
    const layout = buildLayoutState({
        containerWidth: 1200,
        savedWidths: { leftWidth: 900, rightWidth: 900 },
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(layout.documentListWidth, '436px');
    assert.equal(layout.studioCardWidth, '320px');
    assert.equal(layout.chatWidth, '420px');
    assert.equal(
        toPixels(layout.documentListWidth)
            + toPixels(layout.chatWidth)
            + toPixels(layout.studioCardWidth)
            + (RESIZER_WIDTH * RESIZER_COUNT),
        1200,
    );
});

test('container width of 0 uses a proportional safe layout instead of fixed narrow columns', () => {
    const layout = buildLayoutState({
        containerWidth: 0,
        savedWidths: null,
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });

    assert.equal(layout.documentListWidth, '20%');
    assert.equal(layout.studioCardWidth, '25%');
    assert.equal(layout.chatWidth, 'calc(100% - 20% - 25% - 24px)');
    assert.notEqual(layout.chatWidth, `${MIN_CHAT_WIDTH}px`);
});

test('buildDraggedExpandedWidths clamps pointer-move preview widths', () => {
    const dragged = buildDraggedExpandedWidths({
        containerWidth: 1200,
        side: 'left',
        delta: 500,
        startLeftWidth: 300,
        startRightWidth: 320,
    });

    assert.equal(dragged.leftWidth, 436);
    assert.equal(dragged.rightWidth, 320);
    assert.equal(dragged.chatWidth, MIN_CHAT_WIDTH);
});

test('getLayoutCssVariables returns CSS width variables for wrappers', () => {
    const layout = buildLayoutState({
        containerWidth: 1600,
        savedWidths: { leftWidth: 360, rightWidth: 420 },
        isDocumentListCollapsed: false,
        isStudioCardCollapsed: false,
    });
    const vars = getLayoutCssVariables(layout);

    assert.deepEqual(vars, {
        [LEFT_WIDTH_VAR]: '360px',
        [RIGHT_WIDTH_VAR]: '420px',
        [CHAT_WIDTH_VAR]: '796px',
    });
});

test('desktop layout class keeps the route and gutter container full width', () => {
    assert.match(DESKTOP_PAGE_CLASS, /\bw-full\b/);
    assert.match(DESKTOP_PAGE_CLASS, /\bmin-w-0\b/);
    assert.match(DESKTOP_PAGE_CLASS, /\boverflow-hidden\b/);

    const idleClassName = getDesktopLayoutClassName(null);
    assert.match(idleClassName, /\bp-4\b/);
    assert.match(idleClassName, /\bw-full\b/);
    assert.match(idleClassName, /\bmin-w-0\b/);
    assert.match(idleClassName, /\bbox-border\b/);

    const draggingClassName = getDesktopLayoutClassName('left');
    assert.match(draggingClassName, /\bselect-none\b/);
    assert.match(draggingClassName, /\bcursor-col-resize\b/);
});

test('panel shell style keeps flex basis, width, and max width synchronized', () => {
    assert.deepEqual(getPanelShellStyle('var(--documents-left-width)'), {
        flex: '0 0 var(--documents-left-width)',
        width: 'var(--documents-left-width)',
        maxWidth: 'var(--documents-left-width)',
        minWidth: 0,
        overflow: 'hidden',
    });
});

function createStorage() {
    const map = new Map();
    return {
        getItem(key) {
            return map.has(key) ? map.get(key) : null;
        },
        setItem(key, value) {
            map.set(key, value);
        },
    };
}

function toPixels(value) {
    return Number.parseFloat(value.replace('px', ''));
}
