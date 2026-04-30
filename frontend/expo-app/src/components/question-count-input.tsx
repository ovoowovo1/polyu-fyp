import React from 'react';
import { Text, TextInput, View } from 'react-native';

import { commonStyles } from '@/lib/styles';
import { sanitizeCountInput } from '@/lib/studio-utils';

export function QuestionCountInput({
  label,
  value,
  max,
  marks,
  onChange,
}: {
  label: string;
  value: string;
  max: number;
  marks: number;
  onChange: (value: string) => void;
}) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={commonStyles.label}>{label}</Text>
      <TextInput
        keyboardType="number-pad"
        onChangeText={(next) => onChange(sanitizeCountInput(next, max))}
        style={commonStyles.input}
        value={value}
      />
      <Text style={commonStyles.muted}>0-{max} questions, {marks} mark{marks === 1 ? '' : 's'} each</Text>
    </View>
  );
}
