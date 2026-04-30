import React from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { commonStyles } from '@/lib/styles';

export function ModalSheet({
  title,
  children,
  onCancel,
  onSubmit,
  submitting,
  submitDisabled = false,
}: {
  title: string;
  children: React.ReactNode;
  onCancel: () => void;
  onSubmit: () => void;
  submitting: boolean;
  submitDisabled?: boolean;
}) {
  return (
    <View style={commonStyles.modalBackdrop}>
      <View style={commonStyles.modalSheet}>
        <Text selectable style={commonStyles.toolbarTitle}>{title}</Text>
        <ScrollView contentContainerStyle={{ gap: 12 }}>{children}</ScrollView>
        <View style={commonStyles.modalActions}>
          <Pressable accessibilityRole="button" onPress={onCancel} style={commonStyles.secondaryButton}>
            <Text style={commonStyles.secondaryButtonText}>Cancel</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            disabled={submitting || submitDisabled}
            onPress={onSubmit}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              (pressed || submitting || submitDisabled) && commonStyles.pressed,
            ]}>
            <Text style={commonStyles.primaryButtonText}>{submitting ? 'Submitting...' : 'Create'}</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}
