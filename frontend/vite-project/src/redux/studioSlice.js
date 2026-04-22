import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { API_BASE_URL } from '../config';



const initialState = {
    isStudioCardCollapsed: false,
    isQuizReaderOpen: false,
}

const studioSlice = createSlice({
    name: 'studio',
    initialState,
    reducers: {
        toggleStudioCardCollapse: (state) => {
            state.isStudioCardCollapsed = !state.isStudioCardCollapsed;
        },
        setQuizReaderOpen: (state, action) => {
            state.isQuizReaderOpen = action.payload;
        },
        resetStudioState: () => ({ ...initialState }),
    },
});



export const { toggleStudioCardCollapse, setQuizReaderOpen, resetStudioState } = studioSlice.actions;
export default studioSlice.reducer;