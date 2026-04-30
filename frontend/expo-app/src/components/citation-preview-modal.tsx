import React from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { useLanguage } from '@/lib/i18n';
import { colors, commonStyles } from '@/lib/styles';
import type { CitationDetails, DocumentChunk } from '@/lib/types';

export type CitationPreviewState = {
  visible: boolean;
  citationNumber?: number;
  details?: CitationDetails;
  loading: boolean;
  chunk?: DocumentChunk | null;
  error?: string;
};

export const initialCitationPreview: CitationPreviewState = {
  visible: false,
  loading: false,
};

export function CitationPreviewModal({
  state,
  previewSourceName,
  onClose,
  onOpenFullSource,
}: {
  state: CitationPreviewState;
  previewSourceName?: string;
  onClose: () => void;
  onOpenFullSource: () => void;
}) {
  const { t } = useLanguage();

  return (
    <Modal animationType="slide" onRequestClose={onClose} transparent visible={state.visible}>
      <View style={commonStyles.modalBackdrop}>
        <ScrollView contentContainerStyle={commonStyles.modalScrollContent} keyboardShouldPersistTaps="handled">
          <View style={commonStyles.modalSheet}>
            <Text selectable style={commonStyles.toolbarTitle}>
              {t('chat.citationPreviewTitle')}
              {state.citationNumber ? ` [${state.citationNumber}]` : ''}
            </Text>

            <View style={commonStyles.previewCard}>
              {previewSourceName ? (
                <Text selectable style={commonStyles.previewMeta}>
                  {t('chat.citationSource', { source: previewSourceName })}
                </Text>
              ) : null}
              {state.details?.page ? (
                <Text selectable style={commonStyles.previewMeta}>
                  {t('chat.citationPage', { page: state.details.page })}
                </Text>
              ) : null}

              {state.loading ? (
                <ActivityIndicator color={colors.primary} />
              ) : state.chunk?.content ? (
                <View style={commonStyles.previewSnippet}>
                  <Text selectable style={commonStyles.bubbleText}>{state.chunk.content}</Text>
                </View>
              ) : (
                <Text selectable style={commonStyles.muted}>
                  {state.error || t('chat.citationPreviewMissing')}
                </Text>
              )}
            </View>

            <View style={commonStyles.modalActions}>
              <Pressable
                accessibilityRole="button"
                onPress={onClose}
                style={[commonStyles.secondaryButton, commonStyles.modalActionButton]}>
                <Text style={commonStyles.secondaryButtonText}>{t('common.cancel')}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                disabled={!state.details?.fileId}
                onPress={onOpenFullSource}
                style={({ pressed }) => [
                  commonStyles.primaryButton,
                  commonStyles.modalActionButton,
                  !state.details?.fileId && commonStyles.buttonDisabled,
                  pressed && commonStyles.pressed,
                ]}>
                <Text style={commonStyles.primaryButtonText}>{t('chat.openFullSource')}</Text>
              </Pressable>
            </View>
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}
