import React from 'react';
import { List, Typography } from 'antd';
import DocumentStatusIcon from './DocumentStatusIcon';

const { Text } = Typography;

const DocumentListItem = ({
    doc,
    isSelected,
    isCollapsed,
    hoveredDocId,
    dropdownOpen,
    onHover,
    onDropdownChange,
    onViewContent,
    onSelect,
    onDelete,
    onRename,
    onToggleCollapse,
}) => {
    const isHovered = hoveredDocId === doc.id || dropdownOpen === doc.id;

    if (isCollapsed) {
        return (
            <List.Item className={`cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}>
                <div
                    className="items-center w-full"
                    onClick={(e) => {
                        e.stopPropagation();
                        onViewContent(doc.id);
                        onToggleCollapse();
                    }}
                >
                    <DocumentStatusIcon
                        status={doc.status}
                        docId={doc.id}
                        isCollapsed={true}
                        isHovered={isHovered}
                        dropdownOpen={dropdownOpen}
                        onMouseEnter={() => onHover(doc.id)}
                        onMouseLeave={() => {
                            if (dropdownOpen !== doc.id) {
                                onHover(null);
                            }
                        }}
                        onDropdownOpenChange={(open) => onDropdownChange(open ? doc.id : null, doc.id)}
                        onDelete={onDelete}
                        onRename={onRename}
                    />
                </div>
            </List.Item>
        );
    }

    return (
        <List.Item className={`cursor-pointer hover:bg-gray-50 ${isSelected ? 'bg-blue-50' : ''}`}>
            <div className="flex items-center w-full">
                <div className="flex items-center">
                    <DocumentStatusIcon
                        status={doc.status}
                        docId={doc.id}
                        isCollapsed={false}
                        isHovered={isHovered}
                        dropdownOpen={dropdownOpen}
                        onMouseEnter={() => onHover(doc.id)}
                        onMouseLeave={() => {
                            if (dropdownOpen !== doc.id) {
                                onHover(null);
                            }
                        }}
                        onDropdownOpenChange={(open) => onDropdownChange(open ? doc.id : null, doc.id)}
                        onDelete={onDelete}
                        onRename={onRename}
                    />
                </div>
                <div
                    className="flex-1 mx-3 flex items-center min-w-0"
                    onClick={(e) => {
                        e.stopPropagation();
                        onViewContent(doc.id);
                    }}
                >
                    <Text className="text-sm truncate" title={doc.filename}>
                        {doc.filename}
                    </Text>
                </div>
                <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(e) => {
                        e.stopPropagation();
                        onSelect(doc.id, e.target.checked);
                    }}
                    className="mr-2"
                    onClick={(e) => e.stopPropagation()}
                />
            </div>
        </List.Item>
    );
};

export default DocumentListItem;

