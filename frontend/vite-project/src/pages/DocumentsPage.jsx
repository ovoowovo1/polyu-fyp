import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useParams } from 'react-router-dom';
import { selectClassAndLoadDocuments } from '../redux/documentSlice';

import DocumentList from '../components/DocumentList/DocumentList.jsx';
import DocumentsTabs from '../components/DocumentsTabs.jsx';
import Chat from '../components/Chat.jsx';
import StudioCard from '../components/Studio/StudioCard.jsx';
import DocumentsTopBar from '../components/DocumentsTopBar.jsx';

import useMediaQuery from '../hooks/useMediaQuery';
import useLayoutWidth from '../hooks/useLayoutWidth';

const DocumentsPage = () => {
    const { classId } = useParams();
    const dispatch = useDispatch();
    const { isDocumentListCollapsed } = useSelector((state) => state.documents);
    const { isStudioCardCollapsed } = useSelector((state) => state.studio);
    const isMediumScreen = useMediaQuery('(max-width: 1024px)');

    const {
        containerRef,
        layoutStyle,
        leftResizerProps,
        rightResizerProps,
        activeResizer,
    } = useLayoutWidth({
        classId,
        isDocumentListCollapsed,
        isStudioCardCollapsed,
    });

    useEffect(() => {
        if (classId) {
            dispatch(selectClassAndLoadDocuments(classId));
        }
    }, [classId, dispatch]);

    return (
        <>
            {isMediumScreen ? (
                <div className="h-screen flex overflow-hidden bg-gray-100 flex-col">
                    <DocumentsTabs
                        sourcesContent={<DocumentList isMediumScreen={isMediumScreen} />}
                        chatContent={<Chat />}
                    />
                </div>
            ) : (
                <div className="h-screen bg-gray-100 flex flex-col">
                    <DocumentsTopBar />
                    <div
                        ref={containerRef}
                        style={layoutStyle}
                        className={`flex-1 min-h-0 p-4 flex overflow-hidden items-stretch ${activeResizer ? 'select-none cursor-col-resize' : ''}`}
                    >
                        <PanelShell width="var(--documents-left-width)">
                            <DocumentList widthSize="100%" isMediumScreen={isMediumScreen} />
                        </PanelShell>
                        <ResizeHandle side="left" activeResizer={activeResizer} resizerProps={leftResizerProps} />
                        <PanelShell width="var(--documents-chat-width)">
                            <Chat widthSize="100%" />
                        </PanelShell>
                        <ResizeHandle side="right" activeResizer={activeResizer} resizerProps={rightResizerProps} />
                        <PanelShell width="var(--documents-right-width)">
                            <StudioCard widthSize="100%" />
                        </PanelShell>
                    </div>
                </div>
            )}
        </>
    );
};

function PanelShell({ width, children }) {
    return (
        <div
            className="h-full shrink-0 min-w-0"
            style={{ width }}
        >
            {children}
        </div>
    );
}

function ResizeHandle({ side, activeResizer, resizerProps }) {
    return (
        <div
            {...resizerProps}
            className={`h-full shrink-0 px-1 flex items-center justify-center cursor-col-resize group ${activeResizer === side ? 'select-none' : ''}`}
            role="separator"
            aria-orientation="vertical"
        >
            <div
                className={`h-20 w-1 rounded-full transition-colors ${
                    activeResizer === side ? 'bg-blue-500' : 'bg-gray-300 group-hover:bg-gray-400'
                }`}
            />
        </div>
    );
}

export default DocumentsPage;
