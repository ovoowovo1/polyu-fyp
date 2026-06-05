import { apiPost } from './apiClient.js';

export const uploadMultiple = (files, clientId, classId = null) => {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file.originFileObj || file);
  });

  const params = new URLSearchParams();
  if (clientId) params.append('clientId', clientId);
  if (classId) params.append('class_id', classId);

  return apiPost(`/upload-multiple?${params.toString()}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
};


export const uploadLink = (urlToFetch, clientId, classId = null) => {
  const params = new URLSearchParams();
  if (clientId) params.append('clientId', clientId);
  if (classId) params.append('class_id', classId);
  return apiPost(`/upload-link?${params.toString()}`, { url: urlToFetch });
};
