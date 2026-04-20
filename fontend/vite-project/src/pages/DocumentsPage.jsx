import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { selectClassAndLoadDocuments } from '../redux/documentSlice';

import DocumentList from '../components/DocumentList/DocumentList.jsx';
import DocumentsTabs from '../components/DocumentsTabs.jsx';
import Chat from '../components/Chat.jsx';
import StudioCard from '../components/Studio/StudioCard.jsx';
import DocumentsTopBar from '../components/DocumentsTopBar.jsx';

import useMediaQuery from '../hooks/useMediaQuery';
import useLayoutWidth from '../hooks/useLayoutWidth';
import { useParams } from 'react-router-dom';

const DocumentsPage = () => {
    const { classId } = useParams();
    const dispatch = useDispatch();
    const {
        selectedShowDocumentContentID,
        isDocumentListCollapsed,
    } = useSelector((state) => state.documents);
    const { isStudioCardCollapsed, isQuizReaderOpen } = useSelector((state) => state.studio);
    const isMediumScreen = useMediaQuery('(max-width: 1024px)');

    // 使用自定義 Hook 計算佈局寬度
    const { documentListWidth, chatWidth, studioCardWidth } = useLayoutWidth({
        isDocumentListCollapsed,
        isStudioCardCollapsed,
        isQuizReaderOpen,
        selectedShowDocumentContentID,
    });

    useEffect(() => {
        if (classId) {
            // centralized thunk: set current class id and load its documents
            dispatch(selectClassAndLoadDocuments(classId));
        }
    }, [classId, dispatch]);



    return (
        <>
            {
                isMediumScreen ? (
                    <div className={`h-screen flex overflow-hidden bg-gray-100 flex-col`}>
                        <DocumentsTabs
                            sourcesContent={<DocumentList isMediumScreen={isMediumScreen} />}
                            chatContent={<Chat />}
                        />
                    </div>
                ) : (
                    <div className={`h-screen bg-gray-100 flex flex-col`}>
                        <DocumentsTopBar />
                        <div className={`h-screen p-4 flex overflow-hidden gap-4`}
                           >
                            <DocumentList widthSize={documentListWidth} isMediumScreen={isMediumScreen} />
                            <Chat widthSize={chatWidth} />
                            <StudioCard widthSize={studioCardWidth} />
                        </div>
                    </div>
                )}
        </>
    );
};

export default DocumentsPage;