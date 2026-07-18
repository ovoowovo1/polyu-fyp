import React, { memo, useState, useEffect, useMemo } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Card, message } from 'antd';

import {
    fetchDocuments,
    deleteDocument,
    setSearchTerm,
    setSelectedShowDocumentContentID,
    toggleFileSelection,
    toggleSelectAll,
    toggleDocumentListCollapse,
} from '../../redux/documentSlice';
import { getCurrentUser } from '../../api/auth';
import { useTranslation } from 'react-i18next';
import { canUploadSources } from '../../utils/sourceUploadAccess.js';

import {
    areAllFilteredDocumentsSelected,
    filterDocumentsBySearch,
    findDocumentById,
    getFilteredDocumentIds,
    getNextSourceModalVisibility,
    isDocumentSelected,
} from './documentListLogic';
import {
    CollapsedDocumentList,
    DocumentSourceModals,
    ExpandedDocumentList,
} from './DocumentListSections.jsx';

function DocumentList({ widthSize, isMediumScreen }) {
    const { t } = useTranslation();
    const dispatch = useDispatch();
    const {
        items: documents,
        loading,
        error,
        selectedFileIds,
        selectedShowDocumentContentID,
        searchTerm,
        isDocumentListCollapsed,
    } = useSelector((state) => state.documents);

    const user = getCurrentUser();
    const isTeacher = canUploadSources(user);

    const [hoveredDocId, setHoveredDocId] = useState(null);
    const [dropdownOpen, setDropdownOpen] = useState(null);
    const [uploadModalVisible, setUploadModalVisible] = useState(false);
    const [addSourceModalVisible, setAddSourceModalVisible] = useState(false);
    const [linkModalVisible, setLinkModalVisible] = useState(false);
    const [renameModalVisible, setRenameModalVisible] = useState(false);
    const [renamingDoc, setRenamingDoc] = useState(null);

    useEffect(() => {
        if (error) {
            message.error(error);
        }
    }, [error]);

    const filteredDocuments = useMemo(
        () => filterDocumentsBySearch(documents, searchTerm),
        [documents, searchTerm],
    );

    const selectedAll = useMemo(
        () => areAllFilteredDocumentsSelected(filteredDocuments, selectedFileIds),
        [selectedFileIds, filteredDocuments],
    );

    const handleDeleteClick = (docId) => {
        dispatch(deleteDocument(docId)).then(() => {
            message.success(t('documents.fileDeleted'));
        });
    };

    const handleRenameClick = (docId) => {
        const doc = findDocumentById(documents, docId);
        if (doc) {
            setRenamingDoc(doc);
            setRenameModalVisible(true);
        }
    };

    const handleDropdownChange = (open, docId) => {
        setDropdownOpen(open);
        setHoveredDocId(open ? docId : null);
    };

    const handleSelectAll = () => {
        dispatch(toggleSelectAll(getFilteredDocumentIds(filteredDocuments)));
    };

    const handleSourceSelect = (type) => {
        setAddSourceModalVisible(false);
        const nextVisibility = getNextSourceModalVisibility(type);
        setUploadModalVisible(nextVisibility.uploadModalVisible);
        setLinkModalVisible(nextVisibility.linkModalVisible);
    };

    const itemProps = {
        hoveredDocId,
        dropdownOpen,
        isFileSelected: (docId) => isDocumentSelected(selectedFileIds, docId),
        onHover: setHoveredDocId,
        onDropdownChange: handleDropdownChange,
        onViewContent: (id) => dispatch(setSelectedShowDocumentContentID(id)),
        onSelect: (fileId) => dispatch(toggleFileSelection(fileId)),
        onDelete: handleDeleteClick,
        onRename: handleRenameClick,
    };

    const handleFetchDocuments = () => dispatch(fetchDocuments());
    const handleToggleCollapse = () => dispatch(toggleDocumentListCollapse());

    return (
        <>
            <Card
                className="h-full border-r border-gray-100 flex flex-col"
                style={{ width: widthSize || '100%' }}
                hoverable
                styles={{ body: { height: '100%', padding: isDocumentListCollapsed ? '1.5rem 0.75rem' : '1.5rem', display: 'flex', flexDirection: 'column' } }}
            >
                {isDocumentListCollapsed && !isMediumScreen ? (
                    <CollapsedDocumentList
                        t={t}
                        isTeacher={isTeacher}
                        documents={filteredDocuments}
                        loading={loading}
                        itemProps={itemProps}
                        onAddSource={() => setAddSourceModalVisible(true)}
                        onToggleCollapse={handleToggleCollapse}
                    />
                ) : (
                    <ExpandedDocumentList
                        t={t}
                        isTeacher={isTeacher}
                        isMediumScreen={isMediumScreen}
                        documents={filteredDocuments}
                        loading={loading}
                        selectedAll={selectedAll}
                        selectedCount={selectedFileIds.length}
                        selectedShowDocumentContentID={selectedShowDocumentContentID}
                        searchTerm={searchTerm}
                        itemProps={itemProps}
                        onAddSource={() => setAddSourceModalVisible(true)}
                        onSearchChange={(value) => dispatch(setSearchTerm(value))}
                        onSelectAll={handleSelectAll}
                        onToggleCollapse={handleToggleCollapse}
                        onCloseContent={() => dispatch(setSelectedShowDocumentContentID(null))}
                    />
                )}
            </Card>

            <DocumentSourceModals
                uploadModalVisible={uploadModalVisible}
                addSourceModalVisible={addSourceModalVisible}
                linkModalVisible={linkModalVisible}
                renameModalVisible={renameModalVisible}
                renamingDoc={renamingDoc}
                onUploadCancel={() => setUploadModalVisible(false)}
                onUploadSuccess={handleFetchDocuments}
                onAddSourceCancel={() => setAddSourceModalVisible(false)}
                onSourceSelect={handleSourceSelect}
                onLinkCancel={() => setLinkModalVisible(false)}
                onLinkSuccess={handleFetchDocuments}
                onRenameCancel={() => {
                    setRenameModalVisible(false);
                    setRenamingDoc(null);
                }}
            />
        </>
    );
}

export default memo(DocumentList);
