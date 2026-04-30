import type { DocumentChunk } from '@/lib/types';

export function resolveChunkId(chunk: DocumentChunk, index: number) {
  const explicitId = chunk.chunkId ?? chunk.id ?? chunk.file_chunk_id;
  return String(explicitId ?? index);
}
