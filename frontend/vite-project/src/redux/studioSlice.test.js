import test from 'node:test';
import assert from 'node:assert/strict';

import reducer, {
    resetStudioState,
    setQuizReaderOpen,
    toggleStudioCardCollapse,
} from './studioSlice.js';

test('studio slice exposes the expected initial state', () => {
    assert.deepEqual(reducer(undefined, { type: '@@INIT' }), {
        isStudioCardCollapsed: false,
        isQuizReaderOpen: false,
    });
});

test('toggleStudioCardCollapse flips the collapsed state', () => {
    const collapsed = reducer(undefined, toggleStudioCardCollapse());
    const expanded = reducer(collapsed, toggleStudioCardCollapse());

    assert.equal(collapsed.isStudioCardCollapsed, true);
    assert.equal(expanded.isStudioCardCollapsed, false);
});

test('setQuizReaderOpen stores the requested open state', () => {
    const opened = reducer(undefined, setQuizReaderOpen(true));
    const closed = reducer(opened, setQuizReaderOpen(false));

    assert.equal(opened.isQuizReaderOpen, true);
    assert.equal(closed.isQuizReaderOpen, false);
});

test('resetStudioState restores the initial state', () => {
    const dirtyState = {
        isStudioCardCollapsed: true,
        isQuizReaderOpen: true,
    };

    assert.deepEqual(reducer(dirtyState, resetStudioState()), {
        isStudioCardCollapsed: false,
        isQuizReaderOpen: false,
    });
});
