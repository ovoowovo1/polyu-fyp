import * as DocumentPicker from 'expo-document-picker';
import { Redirect, router } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';

import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { useLanguage } from '@/lib/i18n';
import { commonStyles } from '@/lib/styles';

export default function SourceScreen() {
  const { t } = useLanguage();
  const {
    currentClass,
    documents,
    selectedIds,
    refreshing,
    uploadState,
    loadDocuments,
    toggleSelection,
    selectAllDocuments,
    clearSelection,
    uploadPdfFiles,
    uploadLinkUrl,
  } = useDocumentWorkspace();
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState('');
  const [uploadingLink, setUploadingLink] = useState(false);
  const [uploadingPdf, setUploadingPdf] = useState(false);

  useEffect(() => {
    if (!currentClass?.id) return;
    void loadDocuments();
  }, [currentClass?.id, loadDocuments]);

  const selectedCount = selectedIds.length;
  const selectedCountLabel = useMemo(
    () => t('source.selected', { count: selectedCount }),
    [selectedCount, t],
  );

  const allSelected = documents.length > 0 && selectedCount === documents.length;
  const someSelected = selectedCount > 0 && !allSelected;

  const toggleSelectAll = () => {
    if (allSelected || someSelected) {
      clearSelection();
      return;
    }
    selectAllDocuments();
  };

  const pickPdf = async () => {
    if (!currentClass?.id) {
      Alert.alert(t('common.error'), t('source.uploadNoClass'));
      return;
    }

    setUploadingPdf(true);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: 'application/pdf',
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      await uploadPdfFiles(
        result.assets.map((asset) => ({
          uri: asset.uri,
          name: asset.name,
          mimeType: asset.mimeType ?? 'application/pdf',
        })),
      );
    } catch (error) {
      Alert.alert(t('source.pickPdfFailed'), error instanceof Error ? error.message : t('common.unknownError'));
    } finally {
      setUploadingPdf(false);
    }
  };

  const submitLink = async () => {
    const trimmed = linkUrl.trim();
    if (!trimmed) {
      Alert.alert(t('common.error'), t('source.linkRequired'));
      return;
    }

    setUploadingLink(true);
    try {
      await uploadLinkUrl(trimmed);
      setLinkUrl('');
      setLinkModalOpen(false);
    } catch (error) {
      Alert.alert(t('source.uploadFailed'), error instanceof Error ? error.message : t('common.unknownError'));
    } finally {
      setUploadingLink(false);
    }
  };

  if (!currentClass) return <Redirect href="/classes" />;

  return (
    <View style={commonStyles.fullScreen}>
      <FlatList
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={commonStyles.sourceListContent}
        data={documents}
        keyExtractor={(item) => String(item.id)}
        ListHeaderComponent={(
          <View style={commonStyles.sourceHeader}>
            <View style={commonStyles.sourceHeaderMeta}>
              <Text selectable style={commonStyles.toolbarTitle}>{currentClass.name}</Text>
              <Text selectable style={commonStyles.toolbarMeta}>
                {t('workspace.selectedClass')}: {currentClass.id}
              </Text>
            </View>

            <View style={commonStyles.selectionPanel}>
              <Pressable
                accessibilityRole="checkbox"
                accessibilityState={{ checked: allSelected, selected: someSelected }}
                onPress={toggleSelectAll}
                style={({ pressed }) => [commonStyles.selectAllRow, pressed && commonStyles.pressed]}>
                <View
                  style={[
                    commonStyles.checkCircle,
                    commonStyles.selectAllCheckbox,
                    (allSelected || someSelected) && commonStyles.checkCircleActive,
                  ]}>
                  <Text style={commonStyles.checkText}>{allSelected || someSelected ? '✓' : ''}</Text>
                </View>
                <View style={commonStyles.selectAllTextBlock}>
                  <Text selectable style={commonStyles.label}>
                    {allSelected ? t('source.clearAll') : t('source.selectAll')}
                  </Text>
                  <Text selectable style={commonStyles.muted}>{selectedCountLabel}</Text>
                </View>
              </Pressable>
            </View>

            <View style={commonStyles.actionPanel}>
              <View style={commonStyles.sourceActionRow}>
                <Pressable
                  accessibilityRole="button"
                  onPress={pickPdf}
                  style={({ pressed }) => [
                    commonStyles.primaryButton,
                    commonStyles.sourceActionButton,
                    uploadingPdf && commonStyles.buttonDisabled,
                    (pressed || uploadingPdf) && commonStyles.pressed,
                  ]}>
                  <Text style={commonStyles.primaryButtonText}>{t('source.uploadPdf')}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setLinkModalOpen(true)}
                  style={({ pressed }) => [
                    commonStyles.secondaryButton,
                    commonStyles.sourceActionButton,
                    pressed && commonStyles.pressed,
                  ]}>
                  <Text style={commonStyles.secondaryButtonText}>{t('source.uploadLink')}</Text>
                </Pressable>
              </View>
            </View>

            {uploadState.visible && (
              <View style={commonStyles.progressCard}>
                <Text selectable style={commonStyles.label}>{t('source.uploadProgress')}</Text>
                <View style={commonStyles.progressTrack}>
                  <View style={[commonStyles.progressFill, { width: `${uploadState.progress}%` }]} />
                </View>
                <Text selectable style={commonStyles.muted}>
                  {t('source.progressSummary', { done: uploadState.done, total: uploadState.total })}
                </Text>
                {uploadState.currentFile ? (
                  <Text selectable style={commonStyles.muted}>
                    {t('source.progressCurrentFile', { name: uploadState.currentFile })}
                  </Text>
                ) : null}
                {uploadState.summary ? (
                  <Text selectable style={commonStyles.muted}>
                    {t('source.progressResult', {
                      succeeded: uploadState.summary.succeeded ?? 0,
                      failed: uploadState.summary.failed ?? 0,
                    })}
                  </Text>
                ) : null}
                {uploadState.message ? <Text selectable style={commonStyles.muted}>{uploadState.message}</Text> : null}
              </View>
            )}
          </View>
        )}
        ListEmptyComponent={
          <View style={commonStyles.emptyBox}>
            <Text selectable style={commonStyles.emptyTitle}>{t('source.empty')}</Text>
            <Text selectable style={commonStyles.muted}>{t('source.emptyHint')}</Text>
          </View>
        }
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadDocuments(true)} />}
        renderItem={({ item }) => {
          const selected = selectedIds.includes(String(item.id));
          const sourceId = String(item.id);

          return (
            <View style={[commonStyles.card, selected && commonStyles.selectedCard]}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                <Pressable
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: selected }}
                  onPress={() => toggleSelection(sourceId)}
                  style={({ pressed: checkboxPressed }) => [
                    commonStyles.checkCircle,
                    selected && commonStyles.checkCircleActive,
                    checkboxPressed && commonStyles.pressed,
                  ]}>
                  <Text style={commonStyles.checkText}>{selected ? '✓' : ''}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => {
                    router.push({
                      pathname: '/source/[sourceId]',
                      params: {
                        sourceId,
                        name: item.original_name || item.filename || sourceId,
                        status: item.status || '',
                      },
                    });
                  }}
                  style={({ pressed }) => [{ flex: 1, gap: 4 }, pressed && commonStyles.pressed]}>
                  <Text selectable numberOfLines={2} style={commonStyles.itemTitle}>
                    {item.original_name || item.filename || sourceId}
                  </Text>
                </Pressable>
              </View>
            </View>
          );
        }}
      />

      <Modal animationType="slide" onRequestClose={() => setLinkModalOpen(false)} transparent visible={linkModalOpen}>
        <View style={commonStyles.modalBackdrop}>
          <ScrollView contentContainerStyle={commonStyles.modalScrollContent} keyboardShouldPersistTaps="handled">
            <View style={commonStyles.modalSheet}>
              <Text selectable style={commonStyles.toolbarTitle}>{t('source.linkTitle')}</Text>
              <TextInput
                autoCapitalize="none"
                keyboardType="url"
                onChangeText={setLinkUrl}
                placeholder={t('source.linkPlaceholder')}
                style={commonStyles.input}
                value={linkUrl}
              />
              <View style={commonStyles.modalActions}>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setLinkModalOpen(false)}
                  style={[commonStyles.secondaryButton, commonStyles.modalActionButton]}>
                  <Text style={commonStyles.secondaryButtonText}>{t('common.cancel')}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  disabled={uploadingLink}
                  onPress={submitLink}
                  style={({ pressed }) => [
                    commonStyles.primaryButton,
                    commonStyles.modalActionButton,
                    uploadingLink && commonStyles.buttonDisabled,
                    (pressed || uploadingLink) && commonStyles.pressed,
                  ]}>
                  <Text style={commonStyles.primaryButtonText}>{t('common.upload')}</Text>
                </Pressable>
              </View>
            </View>
          </ScrollView>
        </View>
      </Modal>
    </View>
  );
}
