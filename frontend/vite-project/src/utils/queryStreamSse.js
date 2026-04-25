const NEWLINE = /\r\n/g;
const BRACKETED_CITATION = /\[([\d,\s]+)\]/g;

const pushTextPart = (parts, value) => {
  if (!value) {
    return;
  }

  const lastPart = parts[parts.length - 1];
  if (lastPart?.type === 'text') {
    lastPart.value += value;
    return;
  }

  parts.push({ type: 'text', value });
};

const buildCitationPartFromSource = (number, source) => ({
  type: 'citation',
  number,
  details: {
    fileId: source?.fileId,
    chunkId: source?.chunkId,
    source: source?.source,
    page: source?.pageNumber,
  },
});

const stripBracketedTextCitations = (value) => value
  .replace(BRACKETED_CITATION, '')
  .replace(/\s+([.,;:!?])/g, '$1');

const resolveInlineCitationSources = (value, rawSources) => {
  const resolvedSources = [];
  const seenChunkIds = new Set();

  for (const match of value.matchAll(BRACKETED_CITATION)) {
    const parsedNumbers = match[1]
      .split(',')
      .map((item) => item.trim())
      .filter((item) => /^\d+$/.test(item));

    parsedNumbers.forEach((item) => {
      const source = rawSources[Number(item) - 1];
      const chunkId = String(source?.chunkId ?? '');
      if (!chunkId || seenChunkIds.has(chunkId)) {
        return;
      }

      seenChunkIds.add(chunkId);
      resolvedSources.push(source);
    });
  }

  return resolvedSources;
};

const resolveStructuredSegment = (segment, rawSources, sourceByChunkId) => {
  const resolvedSources = [];
  const seenChunkIds = new Set();
  const sourceRefs = segment?.source_references
    || (segment?.source_reference ? [segment.source_reference] : []);

  const pushSource = (source) => {
    const chunkId = String(source?.chunkId ?? '');
    if (!chunkId || seenChunkIds.has(chunkId)) {
      return;
    }

    seenChunkIds.add(chunkId);
    resolvedSources.push(source);
  };

  resolveInlineCitationSources(segment?.segment_text || '', rawSources).forEach(pushSource);
  sourceRefs.forEach((sourceRef) => {
    pushSource(sourceByChunkId.get(String(sourceRef.file_chunk_id)));
  });

  return {
    text: stripBracketedTextCitations(segment?.segment_text || ''),
    sources: resolvedSources,
  };
};

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

export const buildStructuredContentFromTextCitations = (answer, rawSources = []) => {
  const fallbackAnswer = answer || 'Sorry, no answer was returned.';
  const structuredContent = [];
  let cursor = 0;
  let foundValidCitation = false;

  for (const match of fallbackAnswer.matchAll(BRACKETED_CITATION)) {
    const fullMatch = match[0];
    const rawNumbers = match[1];
    const start = match.index ?? -1;

    if (start < 0) {
      continue;
    }

    const parsedNumbers = rawNumbers
      .split(',')
      .map((value) => value.trim());

    const seenNumbers = new Set();
    const uniqueNumbers = [];
    let isValidCitation = parsedNumbers.length > 0;

    for (const value of parsedNumbers) {
      if (!/^\d+$/.test(value)) {
        isValidCitation = false;
        break;
      }

      const citationNumber = Number(value);
      const source = rawSources[citationNumber - 1];
      if (!source) {
        isValidCitation = false;
        break;
      }

      if (!seenNumbers.has(citationNumber)) {
        seenNumbers.add(citationNumber);
        uniqueNumbers.push(citationNumber);
      }
    }

    if (!isValidCitation) {
      continue;
    }

    pushTextPart(structuredContent, fallbackAnswer.slice(cursor, start));
    uniqueNumbers.forEach((citationNumber) => {
      structuredContent.push(
        buildCitationPartFromSource(citationNumber, rawSources[citationNumber - 1]),
      );
    });
    cursor = start + fullMatch.length;
    foundValidCitation = true;
  }

  if (!foundValidCitation) {
    return [{ type: 'text', value: fallbackAnswer }];
  }

  pushTextPart(structuredContent, fallbackAnswer.slice(cursor));
  return structuredContent.length > 0
    ? structuredContent
    : [{ type: 'text', value: fallbackAnswer }];
};

const buildStructuredContentFromAnswerWithCitations = (answerWithCitations, rawSources) => {
  const structuredContent = [];
  const sourceByChunkId = new Map(rawSources.map((source) => [String(source.chunkId), source]));
  const citationRefs = new Map();
  let citationCounter = 1;

  for (const segment of answerWithCitations) {
    const contentSegments = segment?.content_segments || [];
    let accumulatedText = '';

    for (let index = 0; index < contentSegments.length; index += 1) {
      const current = contentSegments[index];
      const next = contentSegments[index + 1];
      const currentResolved = resolveStructuredSegment(current, rawSources, sourceByChunkId);
      const nextResolved = next ? resolveStructuredSegment(next, rawSources, sourceByChunkId) : null;

      accumulatedText += `${currentResolved.text}\n`;

      const currentIds = currentResolved.sources.map((source) => String(source.chunkId)).sort();
      const nextIds = nextResolved
        ? nextResolved.sources.map((source) => String(source.chunkId)).sort()
        : [];
      const sourcesChanged = !next || JSON.stringify(currentIds) !== JSON.stringify(nextIds);

      if (!sourcesChanged) {
        continue;
      }

      pushTextPart(structuredContent, accumulatedText.trim());
      accumulatedText = '';

      const citationParts = currentResolved.sources.map((sourceEntry) => {
        const citationId = String(sourceEntry.chunkId);
        let citationNumber = citationRefs.get(citationId);

        if (!citationNumber) {
          citationNumber = citationCounter;
          citationRefs.set(citationId, citationNumber);
          citationCounter += 1;
        }

        return buildCitationPartFromSource(citationNumber, sourceEntry);
      });

      citationParts
        .sort((left, right) => left.number - right.number)
        .forEach((part) => structuredContent.push(part));
    }
  }

  return structuredContent;
};

export const buildStructuredContentFromResult = (finalResult) => {
  const answerWithCitations = finalResult?.answer_with_citations;
  const rawSources = Array.isArray(finalResult?.raw_sources) ? finalResult.raw_sources : [];

  if (answerWithCitations && answerWithCitations.length > 0) {
    return buildStructuredContentFromAnswerWithCitations(answerWithCitations, rawSources);
  }

  return buildStructuredContentFromTextCitations(finalResult?.answer, rawSources);
};
