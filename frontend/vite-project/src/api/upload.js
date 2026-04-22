import axios from 'axios';
import { API_BASE_URL } from '../config.js';

export const uploadMultiple = (files, clientId, classId = null) => {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file.originFileObj || file);
  });

  const params = new URLSearchParams();
  if (clientId) params.append('clientId', clientId);
  if (classId) params.append('class_id', classId);

  return axios.post(`${API_BASE_URL}/upload-multiple?${params.toString()}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
};


export const uploadLink = (urlToFetch, clientId, classId = null) => {
  const params = new URLSearchParams();
  if (clientId) params.append('clientId', clientId);
  if (classId) params.append('class_id', classId);
  return axios.post(`${API_BASE_URL}/upload-link?${params.toString()}`, { url: urlToFetch });
};

