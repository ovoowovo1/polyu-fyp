import React from 'react';
import { Button, Input, List, Typography } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, ShrinkOutlined } from '@ant-design/icons';

import AddSourceModal from '../AddSourceModal';
import DocumentContentViewer from '../DocumentContentViewer';
import LinkUploadModal from '../LinkUploadModal';
import UploadModal from '../UploadModal';
import RenameModal from './RenameModal';
import DocumentListItem from './DocumentListItem';

const { Title, Text } = Typography;
const { Search } = Input;

function DocumentItems({
    documents,
    loading,
    collapsed,
    hoveredDocId,
    dropdownOpen,
    isFileSelected,
    onHover,
    onDropdownChange,
    onViewContent,
    onSelect,
    onDelete,
    onRename,
    onToggleCollapse,
}) {
    return (
        <List
            split={false}
            loading={loading}
            dataSource={documents}
            renderItem={(doc) => (
                <DocumentListItem
                    doc={doc}
                    isSelected={isFileSelected(doc.id)}
                    isCollapsed={collapsed}
                    hoveredDocId={hoveredDocId}
                    dropdownOpen={dropdownOpen}
                    onHover={onHover}
                    onDropdownChange={onDropdownChange}
                    onViewContent={onViewContent}
                    onSelect={onSelect}
                    onDelete={onDelete}
                    onRename={onRename}
                    onToggleCollapse={onToggleCollapse}
                />
            )}
        />
    );
}

export function CollapsedDocumentList({
    t,
    isTeacher,
    documents,
    loading,
    itemProps,
    onAddSource,
    onToggleCollapse,
}) {
    return (
        <div className="flex flex-col items-center h-full">
            <Button
                onClick={onToggleCollapse}
                shape="circle"
                type="text"
                icon={<MenuUnfoldOutlined />}
                title={t('documents.showDocumentList')}
            />

            {isTeacher && (
                <Button
                    className="ml-auto mt-4"
                    type="primary"
                    icon={<PlusOutlined />}
                    shape="circle"
                    onClick={onAddSource}
                />
            )}

            <DocumentItems
                documents={documents}
                loading={loading}
                collapsed
                onToggleCollapse={onToggleCollapse}
                {...itemProps}
            />
        </div>
    );
}

export function ExpandedDocumentList({
    t,
    isTeacher,
    isMediumScreen,
    documents,
    loading,
    selectedAll,
    selectedCount,
    selectedShowDocumentContentID,
    searchTerm,
    itemProps,
    onAddSource,
    onSearchChange,
    onSelectAll,
    onToggleCollapse,
    onCloseContent,
}) {
    return (
        <>
            <div className="flex mb-4">
                <Title level={4} className="m-0">{t('documents.sources')}</Title>
                <Button
                    className={`ml-auto ${selectedShowDocumentContentID ? 'hidden' : ''} ${isMediumScreen ? 'hidden' : ''}`}
                    onClick={onToggleCollapse}
                    shape="circle"
                    type="text"
                    icon={<MenuFoldOutlined />}
                    title={t('documents.collapseDocumentList')}
                />
                <Button
                    className={`ml-auto ${selectedShowDocumentContentID ? '' : 'hidden'}`}
                    onClick={onCloseContent}
                    shape="circle"
                    type="text"
                    icon={<ShrinkOutlined />}
                />
            </div>
            <DocumentContentViewer selectedShowDocumentContentID={selectedShowDocumentContentID} />
            {!selectedShowDocumentContentID && (
                <>
                    <Search
                        placeholder={t('documents.searchSources')}
                        value={searchTerm}
                        onChange={(event) => onSearchChange(event.target.value)}
                        className="mb-4"
                        allowClear
                    />
                    <div className="flex items-center text-zinc-300 cursor-pointer py-2">
                        <input
                            type="checkbox"
                            checked={selectedAll}
                            onChange={onSelectAll}
                            className="mr-2"
                        />
                        <Text className="text-zinc-300">{t('documents.selectAllSources')}</Text>
                        {isTeacher && (
                            <Button
                                className="ml-auto"
                                type="primary"
                                icon={<PlusOutlined />}
                                onClick={onAddSource}
                            >
                                {t('common.add')}
                            </Button>
                        )}
                    </div>
                    <div className="border-t border-gray-100 flex-1 overflow-y-auto min-h-0">
                        <DocumentItems
                            documents={documents}
                            loading={loading}
                            collapsed={false}
                            onToggleCollapse={onToggleCollapse}
                            {...itemProps}
                        />
                    </div>
                    <div className="p-4 border-t border-gray-100">
                        <Text className="text-zinc-400 text-xs">
                            {t('documents.sourcesCount', { count: documents.length })}
                            {selectedCount > 0 && (
                                <span className="ml-2 text-blue-500">{t('documents.selectedCount', { count: selectedCount })}</span>
                            )}
                        </Text>
                    </div>
                </>
            )}
        </>
    );
}

export function DocumentSourceModals({
    uploadModalVisible,
    addSourceModalVisible,
    linkModalVisible,
    renameModalVisible,
    renamingDoc,
    onUploadCancel,
    onUploadSuccess,
    onAddSourceCancel,
    onSourceSelect,
    onLinkCancel,
    onLinkSuccess,
    onRenameCancel,
}) {
    return (
        <>
            <UploadModal
                visible={uploadModalVisible}
                onCancel={onUploadCancel}
                onSuccess={onUploadSuccess}
            />
            <AddSourceModal
                visible={addSourceModalVisible}
                onCancel={onAddSourceCancel}
                onSelect={onSourceSelect}
            />
            <LinkUploadModal
                visible={linkModalVisible}
                onCancel={onLinkCancel}
                onSuccess={onLinkSuccess}
            />
            <RenameModal
                visible={renameModalVisible}
                onCancel={onRenameCancel}
                docId={renamingDoc?.id}
                currentName={renamingDoc?.filename}
            />
        </>
    );
}
