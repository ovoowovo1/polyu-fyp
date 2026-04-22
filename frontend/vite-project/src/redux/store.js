import { configureStore } from '@reduxjs/toolkit';
import documentsReducer from './documentSlice';
import studioReducer from './studioSlice';

export const store = configureStore({
    reducer: {
        documents: documentsReducer,
        studio: studioReducer,
    },
});
