import { router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';

import { SourceReaderChunk } from '@/components/source-reader-chunk';
import { getDocumentContent } from '@/lib/api';
import { resolveChunkId } from '@/lib/chunk-utils';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { useLanguage } from '@/lib/i18n';
import { colors, commonStyles } from '@/lib/styles';
import type { DocumentDetails } from '@/lib/types';

export default function SourceReaderScreen() {
  const { t } = useLanguage();
  const { sourceId, name, status, chunkId } = useLocalSearchParams<{
    sourceId?: string;
    name?: string;
    status?: string;
    chunkId?: string;
  }>();
  const { documents } = useDocumentWorkspace();
  const [documentData, setDocumentData] = useState<DocumentDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const scrollViewRef = useRef<ScrollView | null>(null);
  const [chunkOffsets, setChunkOffsets] = useState<Record<string, number>>({});
  const hasScrolledRef = useRef(false);

  const document = useMemo(
    () => documents.find((item) => String(item.id) === String(sourceId)),
    [documents, sourceId],
  );

  const title = document?.original_name || document?.filename || name || sourceId || t('source.reader.title');
  const resolvedStatus = status || document?.status || t('source.ready');
  const chunks = documentData?.chunks ?? [];
  const focusedChunkId = chunkId ? String(chunkId) : '';

  useEffect(() => {
    let active = true;

    const loadDocument = async () => {
      if (!sourceId) return;
      setLoading(true);
      setError('');
      hasScrolledRef.current = false;
      setChunkOffsets({});
      try {
        const result = await getDocumentContent(sourceId);
        if (!active) return;
        setDocumentData(result);
      } catch (loadError) {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : t('common.unknownError'));
        setDocumentData(null);
      } finally {
        if (active) setLoading(false);
      }
    };

    void loadDocument();

    return () => {
      active = false;
    };
  }, [sourceId, t]);

  useEffect(() => {
    if (!focusedChunkId || hasScrolledRef.current) {
      return;
    }
    const offset = chunkOffsets[focusedChunkId];
    if (typeof offset !== 'number') {
      return;
    }

    scrollViewRef.current?.scrollTo({ y: Math.max(offset - 24, 0), animated: true });
    hasScrolledRef.current = true;
  }, [chunkOffsets, focusedChunkId]);

  return (
    <View style={commonStyles.fullScreen}>
      <ScrollView ref={scrollViewRef} contentContainerStyle={commonStyles.listContent}>
        <View style={commonStyles.card}>
          <Text selectable style={commonStyles.eyebrow}>{t('source.reader.title')}</Text>
          <Text selectable style={commonStyles.title}>{title}</Text>
          <Text selectable style={commonStyles.subtitle}>
            {t('source.reader.status', { status: resolvedStatus })}
          </Text>
        </View>

        {loading ? (
          <View style={commonStyles.card}>
            <ActivityIndicator color={colors.primary} />
          </View>
        ) : error ? (
          <View style={commonStyles.card}>
            <Text selectable style={commonStyles.emptyTitle}>{t('source.reader.loadFailed')}</Text>
            <Text selectable style={commonStyles.muted}>{error}</Text>
          </View>
        ) : chunks.length > 0 ? (
          <View style={commonStyles.card}>
            <Text selectable style={commonStyles.label}>{t('source.reader.content')}</Text>
            {chunks.map((chunk, index) => {
              const resolvedChunkId = resolveChunkId(chunk, index);
              const isFocused = focusedChunkId.length > 0 && resolvedChunkId === focusedChunkId;

              return (
                <SourceReaderChunk
                  key={`${String(sourceId)}-${resolvedChunkId}`}
                  chunk={chunk}
                  focused={isFocused}
                  onLayout={(offsetY) => {
                    setChunkOffsets((current) => (
                      current[resolvedChunkId] === offsetY ? current : { ...current, [resolvedChunkId]: offsetY }
                    ));
                  }}
                />
              );
            })}
          </View>
        ) : (
          <View style={commonStyles.card}>
            <Text selectable style={commonStyles.emptyTitle}>{title}</Text>
            <Text selectable style={commonStyles.muted}>{t('source.reader.noContent')}</Text>
          </View>
        )}

        <Pressable accessibilityRole="button" onPress={() => router.back()} style={commonStyles.secondaryButton}>
          <Text style={commonStyles.secondaryButtonText}>{t('common.cancel')}</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}
