import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { API_BASE_URL } from '../config.js';
import { dedupe } from '../utils/requestDeduper.js';

// 異步 Thunk 用於從 API 獲取文件
export const fetchDocuments = createAsyncThunk(
    'documents/fetchDocuments',
    // arg can be an optional classId; if not provided, read from state
    async (classId = null, { rejectWithValue, getState }) => {
        try {
            const state = getState();

            const cid = classId || state.documents?.currentClassId || null;
            const key = `docs:list:${cid || '__all__'}`;

            const params = {};
            if (cid) params.class_id = cid;



            // use dedupe utility; return an array of files (not axios response)
            return dedupe(key, () => axios.get(`${API_BASE_URL}/files`, { params }).then(r => r.data.files || []), { ttl: 500 });
        } catch (error) {
            console.error('Fetch documents error:', error);
            return rejectWithValue('載入文件列表失敗');
        }
    }
);

// 異步 Thunk 用於刪除文件
export const deleteDocument = createAsyncThunk(
    'documents/deleteDocument',
    async (docId, { rejectWithValue }) => {
        try {
            await axios.delete(`${API_BASE_URL}/files/${docId}`);
            return docId;
        } catch (error) {
            console.error('Delete document error:', error);
            return rejectWithValue('刪除文件失敗');
        }
    }
);

export const renameDocument = createAsyncThunk(
    'documents/renameDocument',
    async ({ docId, newName }, { rejectWithValue }) => {
        try {
            await axios.put(`${API_BASE_URL}/files/${docId}`, null, {
                params: { new_name: newName }
            });
            return { docId, newName };
        } catch (error) {
            console.error('Rename document error:', error);
            return rejectWithValue('重新命名文件失敗');
        }
    }
);

export const fetchDocumentContent = createAsyncThunk(
    'document/fetchDocumentContent',
    async (docId, { rejectWithValue }) => {
        if (!docId) {
            return null;
        }
        try {
            const response = await axios.get(`${API_BASE_URL}/files/${docId}`);
            return response.data;
        } catch (error) {
            return rejectWithValue(error.response.data);
        }
    }
);

const initialState = {
    items: [],
    documentsById: {},
    currentClassId: null,
    loading: false, // for document list
    contentLoading: false, // for document content viewer
    error: null,
    selectedFileIds: [],
    selectedShowDocumentContentID: null,
    searchTerm: '',
    isDocumentListCollapsed: false, // for collapsing document list
}

const documentsSlice = createSlice({
    name: 'documents',
    initialState,
    reducers: {
        setSearchTerm: (state, action) => {
            state.searchTerm = action.payload;
        },
        setSelectedShowDocumentContentID: (state, action) => {
            state.selectedShowDocumentContentID = action.payload;
        },
        toggleFileSelection: (state, action) => {
            const fileId = action.payload;
            const index = state.selectedFileIds.indexOf(fileId);
            if (index >= 0) {
                state.selectedFileIds.splice(index, 1);
            } else {
                state.selectedFileIds.push(fileId);
            }
        },
        toggleSelectAll: (state, action) => {
            const allFileIds = action.payload;
            if (state.selectedFileIds.length === allFileIds.length) {
                state.selectedFileIds = [];
            } else {
                state.selectedFileIds = allFileIds;
            }
        },
        toggleDocumentListCollapse: (state) => {
            state.isDocumentListCollapsed = !state.isDocumentListCollapsed;
        },
        setCurrentClassId: (state, action) => {
            state.currentClassId = action.payload;
        },
        resetDocumentState: () => {
            return { ...initialState }
        },
    },
    extraReducers: (builder) => {
        builder
            .addCase(fetchDocuments.pending, (state) => {
                state.loading = true;
                state.error = null;
            })
            .addCase(fetchDocuments.fulfilled, (state, action) => {
                state.loading = false;
                state.items = action.payload;
            })
            .addCase(fetchDocuments.rejected, (state, action) => {
                state.loading = false;
                state.error = action.payload;
                state.items = [];
            })
            .addCase(deleteDocument.fulfilled, (state, action) => {
                state.items = state.items.filter(doc => doc.id !== action.payload);
            })
            .addCase(deleteDocument.rejected, (state, action) => {
                state.error = action.payload;
                console.error(action.payload);
            })
            .addCase(renameDocument.fulfilled, (state, action) => {
                const { docId, newName } = action.payload;
                const doc = state.items.find(doc => doc.id === docId);
                if (doc) {
                    doc.filename = newName;
                    doc.original_name = newName;
                }
            })
            .addCase(renameDocument.rejected, (state, action) => {
                state.error = action.payload;
                console.error(action.payload);
            })
            .addCase(fetchDocumentContent.pending, (state) => {
                state.contentLoading = true;
                state.error = null;
            })
            .addCase(fetchDocumentContent.fulfilled, (state, action) => {
                state.contentLoading = false;
                if (action.payload) {
                    const docId = action.payload.file.id;
                    state.documentsById[docId] = action.payload;
                }
            })
            .addCase(fetchDocumentContent.rejected, (state, action) => {
                state.contentLoading = false;
                state.error = action.payload;
            });
    },
});

export const {
    setSearchTerm,
    setSelectedShowDocumentContentID,
    toggleFileSelection,
    toggleSelectAll,
    toggleDocumentListCollapse,
    setCurrentClassId,
    resetDocumentState,
} = documentsSlice.actions;

// Thunk to select a class and then load its documents
export const selectClassAndLoadDocuments = (classId) => async (dispatch) => {
    dispatch(setCurrentClassId(classId));
    // dispatch fetchDocuments and wait for it to complete
    await dispatch(fetchDocuments(classId));
};

export default documentsSlice.reducer;
