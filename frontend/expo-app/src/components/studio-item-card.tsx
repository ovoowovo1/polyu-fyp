import React from 'react';
import { Pressable, Text, View } from 'react-native';

import { colors, commonStyles } from '@/lib/styles';
import { type StudioItem, formatStudioDate } from '@/lib/studio-utils';
import { StudioTag } from '@/components/studio-tag';

export function StudioItemCard({
  item,
  onPress,
}: {
  item: StudioItem;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [commonStyles.card, pressed && commonStyles.pressed]}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <View style={{ flex: 1, gap: 6 }}>
          <Text selectable numberOfLines={2} style={commonStyles.itemTitle}>
            {item.title}
          </Text>
          <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
            <StudioTag label={item.type === 'exam' ? 'Exam' : 'Quiz'} color={item.type === 'exam' ? '#dbeafe' : '#dcfce7'} />
            <StudioTag label={`${item.raw.num_questions ?? 0} questions`} color="#f1f5f9" />
            {item.type === 'exam' && (
              <StudioTag
                label={item.raw.is_published ? 'Published' : 'Draft'}
                color={item.raw.is_published ? '#dcfce7' : '#f8fafc'}
              />
            )}
          </View>
          <Text selectable style={commonStyles.muted}>
            {formatStudioDate(item.createdAt)}
          </Text>
          {item.raw.documents && item.raw.documents.length > 0 && (
            <Text selectable numberOfLines={1} style={commonStyles.muted}>
              Sources: {item.raw.documents.map((document) => document.name).filter(Boolean).join(', ')}
            </Text>
          )}
        </View>
        <Text style={{ color: colors.primary, fontSize: 22 }}>{'>'}</Text>
      </View>
    </Pressable>
  );
}
