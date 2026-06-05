export function filterDocumentsBySearch(documents, searchTerm) {
    const normalizedTerm = String(searchTerm || '').toLowerCase();
    return documents.filter((doc) => String(doc.filename || '').toLowerCase().includes(normalizedTerm));
}

export function isDocumentSelected(selectedFileIds, docId) {
    return selectedFileIds.includes(docId);
}

export function areAllFilteredDocumentsSelected(filteredDocuments, selectedFileIds) {
    return filteredDocuments.length > 0 && selectedFileIds.length === filteredDocuments.length;
}

export function findDocumentById(documents, docId) {
    return documents.find((doc) => doc.id === docId) || null;
}

export function getFilteredDocumentIds(filteredDocuments) {
    return filteredDocuments.map((doc) => doc.id);
}

export function getNextSourceModalVisibility(type) {
    return {
        uploadModalVisible: type === 'pdf',
        linkModalVisible: type === 'link',
    };
}
