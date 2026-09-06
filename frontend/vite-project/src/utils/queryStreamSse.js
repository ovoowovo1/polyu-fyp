const NEWLINE = /\r\n/g;

export const splitSseFrames = (buffer) => {
  const normalized = buffer.replace(NEWLINE, '\n');
  const frames = [];
  let start = 0;

  while (true) {
    const boundary = normalized.indexOf('\n\n', start);
    if (boundary === -1) {
      break;
    }
    frames.push(normalized.slice(start, boundary));
    start = boundary + 2;
  }

  return {
    frames,
    remainder: normalized.slice(start),
  };
};

export const parseSseFrame = (frame) => {
  if (!frame || !frame.trim()) {
    return null;
  }

  let eventName = 'message';
  const dataLines = [];

  frame.split('\n').forEach((line) => {
    if (!line || line.startsWith(':')) {
      return;
    }

    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim() || 'message';
      return;
    }

    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart());
    }
  });

  if (dataLines.length === 0) {
    return null;
  }

  const rawData = dataLines.join('\n');
  try {
    const parsed = JSON.parse(rawData);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) && !parsed.type) {
      parsed.type = eventName;
    }
    return parsed;
  } catch {
    return {
      type: eventName,
      message: rawData,
    };
  }
};

export const readSseStream = async (stream, { onEvent } = {}) => {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const { frames, remainder } = splitSseFrames(buffer);
      buffer = remainder;

      for (const frame of frames) {
        const parsed = parseSseFrame(frame);
        if (!parsed) {
          continue;
        }
        events.push(parsed);
        if (onEvent) {
          onEvent(parsed);
        }
      }
    }

    const trailing = parseSseFrame(buffer.trim());
    if (trailing) {
      events.push(trailing);
      if (onEvent) {
        onEvent(trailing);
      }
    }
  } finally {
    reader.releaseLock();
  }

  return events;
};

export const buildStructuredContentFromResult = (result) => {
  if (!['complete', 'partial', 'unavailable'].includes(result?.status)
    || !Array.isArray(result.blocks) || !Array.isArray(result.sources)
    || !Array.isArray(result.limitations) || typeof result.trace_id !== 'string') {
    throw new Error('Invalid RAG result. Please retry.');
  }
  const sources = new Map();
  for (const source of result.sources) {
    if (!source.chunk_id || !source.file_id || typeof source.content !== 'string'
      || sources.has(source.chunk_id)) throw new Error('Invalid RAG sources.');
    sources.set(source.chunk_id, source);
  }
  const numbers = new Map();
  const ids = new Set();
  const parts = [];
  for (const block of result.blocks) {
    if (!block.id || ids.has(block.id) || typeof block.markdown !== 'string'
      || !Array.isArray(block.source_ids)) throw new Error('Invalid RAG block.');
    ids.add(block.id);
    parts.push({ type: 'text', value: block.markdown });
    for (const id of new Set(block.source_ids)) {
      const source = sources.get(id);
      if (!source) throw new Error('RAG citation source is missing.');
      if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
      parts.push({ type: 'citation', number: numbers.get(id), details: {
        chunkId: id, fileId: source.file_id, source: source.name,
        page: source.page_start, pageEnd: source.page_end, content: source.content,
        imageData: source.image_data,
      } });
    }
  }
  return parts;
};
