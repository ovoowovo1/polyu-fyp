import { Redirect, router } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';

import { askQuestion, getDocumentContent } from '@/lib/api';
import { resolveChunkId } from '@/lib/chunk-utils';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { useLanguage } from '@/lib/i18n';
import { colors, commonStyles } from '@/lib/styles';
import type { CitationDetails, ChatMessage, ProgressEvent } from '@/lib/types';
import {
  CitationPreviewModal,
  initialCitationPreview,
  type CitationPreviewState,
} from '@/components/citation-preview-modal';
import { ChatMessageBubble } from '@/components/chat-message-bubble';

export default function ChatScreen() {
  const { t } = useLanguage();
  const { currentClass, documents, selectedIds } = useDocumentWorkspace();
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [keyboardBottom, setKeyboardBottom] = useState(0);
  const [citationPreview, setCitationPreview] = useState<CitationPreviewState>(initialCitationPreview);

  useEffect(() => {
    if (Platform.OS !== 'android') {
      return undefined;
    }

    const showSubscription = Keyboard.addListener('keyboardDidShow', (event) => {
      setKeyboardBottom(event.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setKeyboardBottom(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  const welcomeText = useMemo(() => {
    if (documents.length === 0) {
      return t('chat.welcomeNoDocuments');
    }
    if (selectedIds.length === 0) {
      return t('chat.welcomeNoSelection', { count: documents.length });
    }
    return t('chat.welcomeSelected', { selected: selectedIds.length, count: documents.length });
  }, [documents.length, selectedIds.length, t]);

  const previewSourceName = useMemo(() => {
    if (!citationPreview.details?.fileId) {
      return citationPreview.details?.source;
    }
    const document = documents.find((item) => String(item.id) === String(citationPreview.details?.fileId));
    return document?.original_name || document?.filename || citationPreview.details?.source;
  }, [citationPreview.details?.fileId, citationPreview.details?.source, documents]);

  const submitQuestion = async () => {
    const trimmed = question.trim();
    if (!trimmed || asking) {
      return;
    }
    if (selectedIds.length === 0) {
      Alert.alert(t('chat.selectDocumentTitle'), t('chat.selectDocumentMessage'));
      router.navigate('/source');
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: trimmed,
    };
    setMessages((current) => [...current, userMessage]);
    setQuestion('');
    setAsking(true);
    setProgress([]);

    try {
      const answer = await askQuestion({
        question: trimmed,
        selectedFileIds: selectedIds,
        documentCount: documents.length,
        selectedCount: selectedIds.length,
        onProgress: (event) => setProgress((current) => [...current, event]),
      });
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          parts: answer,
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-error-${Date.now()}`,
          role: 'assistant',
          text: error instanceof Error ? error.message : t('common.unknownError'),
        },
      ]);
    } finally {
      setAsking(false);
    }
  };

  const openCitationPreview = async (number: number, details?: CitationDetails) => {
    if (!details?.fileId || !details.chunkId) {
      setCitationPreview({
        visible: true,
        citationNumber: number,
        details,
        loading: false,
        chunk: null,
        error: t('chat.citationPreviewUnavailable'),
      });
      return;
    }

    setCitationPreview({
      visible: true,
      citationNumber: number,
      details,
      loading: true,
      chunk: null,
      error: '',
    });

    try {
      const result = await getDocumentContent(String(details.fileId));
      const chunk = (result.chunks ?? []).find((item, index) => (
        resolveChunkId(item, index) === String(details.chunkId)
      ));

      setCitationPreview({
        visible: true,
        citationNumber: number,
        details,
        loading: false,
        chunk: chunk ?? null,
        error: chunk ? '' : t('chat.citationPreviewMissing'),
      });
    } catch (error) {
      setCitationPreview({
        visible: true,
        citationNumber: number,
        details,
        loading: false,
        chunk: null,
        error: error instanceof Error ? error.message : t('common.unknownError'),
      });
    }
  };

  const openFullSource = () => {
    if (!citationPreview.details?.fileId) {
      return;
    }

    const document = documents.find((item) => String(item.id) === String(citationPreview.details?.fileId));
    setCitationPreview(initialCitationPreview);
    router.push({
      pathname: '/source/[sourceId]',
      params: {
        sourceId: String(citationPreview.details.fileId),
        chunkId: citationPreview.details.chunkId ? String(citationPreview.details.chunkId) : undefined,
        citationNumber: citationPreview.citationNumber ? String(citationPreview.citationNumber) : undefined,
        name: document?.original_name || document?.filename || citationPreview.details.source || '',
        status: document?.status || '',
      },
    });
  };

  if (!currentClass) {
    return <Redirect href="/classes" />;
  }

  return (
    <View style={commonStyles.fullScreen}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 88 : 0}
        style={{ flex: 1 }}>
        <ScrollView
          contentInsetAdjustmentBehavior="automatic"
          contentContainerStyle={commonStyles.chatContent}
          keyboardShouldPersistTaps="handled">
          <View style={[commonStyles.card, { gap: 4 }]}>
            <Text selectable style={commonStyles.toolbarTitle}>
              {currentClass.name}
            </Text>
            <Text selectable style={commonStyles.muted}>{welcomeText}</Text>
          </View>

          {messages.map((message) => (
            <ChatMessageBubble
              key={message.id}
              message={message}
              onPressCitation={(number, details) => {
                void openCitationPreview(number, details);
              }}
            />
          ))}

          {asking && (
            <View style={[commonStyles.bubble, commonStyles.assistantBubble, commonStyles.loadingBubble]}>
              <ActivityIndicator color={colors.primary} size="small" />
              <Text selectable style={commonStyles.muted}>
                {progress.length > 0 ? t('chat.progress') : t('chat.thinking')}
              </Text>
            </View>
          )}
        </ScrollView>

        {selectedIds.length === 0 && (
          <Text selectable style={commonStyles.composerHint}>{t('chat.selectDocumentHint')}</Text>
        )}

        <View style={[commonStyles.composer, keyboardBottom > 0 && { marginBottom: keyboardBottom }]}>
          {messages.length > 0 && (
            <Pressable accessibilityRole="button" onPress={() => setMessages([])} style={commonStyles.secondaryButton}>
              <Text style={commonStyles.secondaryButtonText}>{t('chat.clear')}</Text>
            </Pressable>
          )}
          <TextInput
            multiline
            editable
            onChangeText={setQuestion}
            placeholder={t('chat.placeholder')}
            style={[commonStyles.input, { flex: 1, minHeight: 44, maxHeight: 120 }]}
            value={question}
          />
          <Pressable
            accessibilityRole="button"
            disabled={asking || !question.trim() || selectedIds.length === 0}
            onPress={submitQuestion}
            style={({ pressed }) => [
              commonStyles.sendButton,
              (pressed || asking || !question.trim() || selectedIds.length === 0) && commonStyles.pressed,
            ]}>
            <Text style={commonStyles.primaryButtonText}>{t('chat.send')}</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>

      <CitationPreviewModal
        state={citationPreview}
        previewSourceName={previewSourceName}
        onClose={() => setCitationPreview(initialCitationPreview)}
        onOpenFullSource={openFullSource}
      />
    </View>
  );
}
