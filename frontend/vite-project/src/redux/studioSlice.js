import { createSlice } from '@reduxjs/toolkit';



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
