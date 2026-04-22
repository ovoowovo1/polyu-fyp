import { API_BASE_URL } from '../config.js';

export const openProgressSSE = (clientId, { onMessage, onError } = {}) => {
  const es = new EventSource(`${API_BASE_URL}/sse/progress?clientId=${encodeURIComponent(clientId)}`);
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data || '{}');
      onMessage && onMessage(data);
    } catch (err) {
      // ignore
    }
  };
  es.onerror = (e) => {
    try { es.close(); } catch {}
    onError && onError(e);
  };
  return es;
};

export const closeSSE = (es) => {
  if (!es) return;
  try { es.close(); } catch {}
};


