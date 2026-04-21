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

export const buildStructuredContentFromResult = (finalResult) => {
  const answerWithCitations = finalResult?.answer_with_citations;
  const structuredContent = [];
  const rawSources = Array.isArray(finalResult?.raw_sources) ? finalResult.raw_sources : [];
  const sourceByChunkId = new Map(rawSources.map((source) => [String(source.chunkId), source]));

  if (!answerWithCitations || answerWithCitations.length === 0) {
    structuredContent.push({
      type: 'text',
      value: finalResult?.answer || 'Sorry, no answer was returned.',
    });
    return structuredContent;
  }

  const citationRefs = new Map();
  let citationCounter = 1;

  for (const segment of answerWithCitations) {
    const contentSegments = segment?.content_segments || [];
    let accumulatedText = '';

    for (let index = 0; index < contentSegments.length; index += 1) {
      const current = contentSegments[index];
      const next = contentSegments[index + 1];

      accumulatedText += `${current.segment_text}\n`;

      const sourceRefs = current.source_references
        || (current.source_reference ? [current.source_reference] : []);
      const nextSourceRefs = next?.source_references
        || (next?.source_reference ? [next.source_reference] : []);

      const currentIds = sourceRefs.map((source) => source.file_chunk_id).sort();
      const nextIds = nextSourceRefs.map((source) => source.file_chunk_id).sort();
      const sourcesChanged = !next || JSON.stringify(currentIds) !== JSON.stringify(nextIds);

      if (!sourcesChanged) {
        continue;
      }

      structuredContent.push({ type: 'text', value: accumulatedText.trim() });
      accumulatedText = '';

      sourceRefs.forEach((sourceRef) => {
        const citationId = sourceRef.file_chunk_id;
        let citationNumber = citationRefs.get(citationId);

        if (!citationNumber) {
          citationNumber = citationCounter;
          citationRefs.set(citationId, citationNumber);
          citationCounter += 1;
        }

        const sourceEntry = sourceByChunkId.get(String(citationId));
        structuredContent.push({
          type: 'citation',
          number: citationNumber,
          details: {
            fileId: sourceEntry?.fileId,
            chunkId: citationId,
            source: sourceEntry?.source,
            page: sourceEntry?.pageNumber,
          },
        });
      });
    }
  }

  return structuredContent;
};
