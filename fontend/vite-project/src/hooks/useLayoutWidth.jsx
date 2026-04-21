import { useEffect, useMemo, useRef, useState } from 'react';
import {
    buildLayoutState,
    buildDraggedExpandedWidths,
    clampWidths,
    getLayoutCssVariables,
    getMeasuredPanelWidth,
    getDefaultExpandedWidths,
    getLayoutStorageKey,
    loadSavedExpandedWidths,
    saveExpandedWidths,
} from '../utils/documentsLayoutModel.js';

export default function useLayoutWidth({
    classId,
    isDocumentListCollapsed,
    isStudioCardCollapsed,
}) {
    const containerRef = useRef(null);
    const dragStateRef = useRef(null);
    const storageKey = useMemo(() => getLayoutStorageKey(classId), [classId]);
    const [containerWidth, setContainerWidth] = useState(0);
    const [expandedWidths, setExpandedWidths] = useState(() => (
        loadSavedExpandedWidths(globalThis?.localStorage, storageKey)
    ));
    const [activeResizer, setActiveResizer] = useState(null);
    const pendingWidthsRef = useRef(null);
    const frameRef = useRef(null);

    useEffect(() => {
        setExpandedWidths(loadSavedExpandedWidths(globalThis?.localStorage, storageKey));
    }, [storageKey]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return undefined;
        }

        const updateWidth = () => {
            const styles = window.getComputedStyle(container);
            const paddingLeft = Number.parseFloat(styles.paddingLeft) || 0;
            const paddingRight = Number.parseFloat(styles.paddingRight) || 0;
            const measuredWidth = container.getBoundingClientRect().width;

            setContainerWidth(getMeasuredPanelWidth({
                measuredWidth,
                paddingLeft,
                paddingRight,
            }));
        };

        updateWidth();

        const resizeObserver = new ResizeObserver(updateWidth);
        resizeObserver.observe(container);

        return () => resizeObserver.disconnect();
    }, []);

    const layout = useMemo(() => buildLayoutState({
        containerWidth,
        savedWidths: expandedWidths,
        isDocumentListCollapsed,
        isStudioCardCollapsed,
    }), [containerWidth, expandedWidths, isDocumentListCollapsed, isStudioCardCollapsed]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }

        const nextVars = getLayoutCssVariables(layout);
        Object.entries(nextVars).forEach(([key, value]) => {
            container.style.setProperty(key, value);
        });
    }, [layout]);

    useEffect(() => {
        if (containerWidth <= 0) {
            return;
        }

        const defaults = getDefaultExpandedWidths(containerWidth);
        const clamped = clampWidths({
            containerWidth,
            leftWidth: expandedWidths?.leftWidth ?? defaults.leftWidth,
            rightWidth: expandedWidths?.rightWidth ?? defaults.rightWidth,
        });

        if (
            !expandedWidths ||
            expandedWidths.leftWidth !== clamped.leftWidth ||
            expandedWidths.rightWidth !== clamped.rightWidth
        ) {
            setExpandedWidths({
                leftWidth: clamped.leftWidth,
                rightWidth: clamped.rightWidth,
            });
            saveExpandedWidths(globalThis?.localStorage, storageKey, clamped);
        }
    }, [containerWidth, expandedWidths, storageKey]);

    useEffect(() => {
        if (!activeResizer) {
            return undefined;
        }

        const applyPendingWidths = () => {
            frameRef.current = null;
            if (!pendingWidthsRef.current || !containerRef.current) {
                return;
            }

            const previewLayout = buildLayoutState({
                containerWidth,
                savedWidths: {
                    leftWidth: pendingWidthsRef.current.leftWidth,
                    rightWidth: pendingWidthsRef.current.rightWidth,
                },
                isDocumentListCollapsed,
                isStudioCardCollapsed,
            });
            const nextVars = getLayoutCssVariables(previewLayout);
            Object.entries(nextVars).forEach(([key, value]) => {
                containerRef.current.style.setProperty(key, value);
            });
        };

        const schedulePreview = () => {
            if (frameRef.current != null) {
                return;
            }
            frameRef.current = window.requestAnimationFrame(applyPendingWidths);
        };

        const handlePointerMove = (event) => {
            const dragState = dragStateRef.current;
            if (!dragState) {
                return;
            }

            const delta = event.clientX - dragState.startX;
            pendingWidthsRef.current = buildDraggedExpandedWidths({
                containerWidth,
                side: dragState.side,
                delta,
                startLeftWidth: dragState.startLeftWidth,
                startRightWidth: dragState.startRightWidth,
            });
            schedulePreview();
        };

        const stopDragging = () => {
            if (frameRef.current != null) {
                window.cancelAnimationFrame(frameRef.current);
                frameRef.current = null;
            }

            const pendingWidths = pendingWidthsRef.current;
            if (pendingWidths) {
                setExpandedWidths({
                    leftWidth: pendingWidths.leftWidth,
                    rightWidth: pendingWidths.rightWidth,
                });
                saveExpandedWidths(globalThis?.localStorage, storageKey, pendingWidths);
            }

            setActiveResizer(null);
            dragStateRef.current = null;
            pendingWidthsRef.current = null;
        };

        window.addEventListener('pointermove', handlePointerMove);
        window.addEventListener('pointerup', stopDragging);

        return () => {
            window.removeEventListener('pointermove', handlePointerMove);
            window.removeEventListener('pointerup', stopDragging);
            if (frameRef.current != null) {
                window.cancelAnimationFrame(frameRef.current);
                frameRef.current = null;
            }
        };
    }, [activeResizer, containerWidth, isDocumentListCollapsed, isStudioCardCollapsed, storageKey]);

    useEffect(() => {
        if (!expandedWidths) {
            return;
        }

        saveExpandedWidths(globalThis?.localStorage, storageKey, expandedWidths);
    }, [expandedWidths, storageKey]);

    useEffect(() => {
        if (!activeResizer) {
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
            return undefined;
        }

        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';

        return () => {
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        };
    }, [activeResizer]);

    const startDragging = (side) => (event) => {
        event.preventDefault();
        dragStateRef.current = {
            side,
            startX: event.clientX,
            startLeftWidth: layout.expandedLeftWidth,
            startRightWidth: layout.expandedRightWidth,
        };
        setActiveResizer(side);
    };

    return {
        containerRef,
        layoutStyle: getLayoutCssVariables(layout),
        leftResizerProps: {
            onPointerDown: startDragging('left'),
            'data-resizer': 'left',
            'aria-label': 'Resize document list and chat panels',
        },
        rightResizerProps: {
            onPointerDown: startDragging('right'),
            'data-resizer': 'right',
            'aria-label': 'Resize chat and studio panels',
        },
        activeResizer,
    };
}
