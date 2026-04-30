import React from 'react';
import { Text, View } from 'react-native';

import { colors } from '@/lib/styles';

export function StudioTag({ label, color }: { label: string; color: string }) {
  return (
    <View style={{ backgroundColor: color, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 }}>
      <Text style={{ color: colors.text, fontSize: 12, fontWeight: '700' }}>{label}</Text>
    </View>
  );
}
