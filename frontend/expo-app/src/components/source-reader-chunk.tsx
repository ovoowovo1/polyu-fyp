import React from 'react';
import { Text, View } from 'react-native';

import { useLanguage } from '@/lib/i18n';
import { commonStyles } from '@/lib/styles';
import type { DocumentChunk } from '@/lib/types';

export function SourceReaderChunk({
  chunk,
  focused,
  onLayout,
}: {
  chunk: DocumentChunk;
  focused: boolean;
  onLayout: (offsetY: number) => void;
}) {
  const { t } = useLanguage();

  return (
    <View
      onLayout={(event) => onLayout(event.nativeEvent.layout.y)}
      style={[commonStyles.readerChunk, focused && commonStyles.readerChunkFocused]}>
      {focused ? (
        <Text selectable style={commonStyles.readerChunkLabel}>
          {t('source.reader.focused')}
        </Text>
      ) : null}
      <Text selectable style={[commonStyles.bubbleText, { fontFamily: 'monospace' }]}>
        {chunk.content || ''}
      </Text>
    </View>
  );
}
