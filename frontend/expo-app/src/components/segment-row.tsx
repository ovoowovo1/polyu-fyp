import React from 'react';
import { Pressable, Text, View } from 'react-native';

import { commonStyles } from '@/lib/styles';

export function SegmentRow({
  options,
  selected,
  onSelect,
}: {
  options: readonly string[];
  selected: string;
  onSelect: (value: string) => void;
}) {
  return (
    <View style={commonStyles.segmented}>
      {options.map((option) => (
        <Pressable
          key={option}
          accessibilityRole="button"
          onPress={() => onSelect(option)}
          style={[commonStyles.segment, selected === option && commonStyles.segmentActive]}>
          <Text style={[commonStyles.segmentText, selected === option && commonStyles.segmentTextActive]}>
            {option}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
