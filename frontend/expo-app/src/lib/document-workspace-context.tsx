import React, { createContext, PropsWithChildren, useCallback, useContext, useMemo, useState } from 'react';
import { Alert } from 'react-native';

import { listDocuments, subscribeUploadProgress, uploadLink, uploadMultiple } from '@/lib/api';
import { useLanguage } from '@/lib/i18n';
import type { ClassSummary, DocumentSummary, UploadProgressState } from '@/lib/types';

type WorkspaceContextValue = {
  currentClass: ClassSummary | null;
  documents: DocumentSummary[];
  selectedIds: string[];
  loading: boolean;
  refreshing: boolean;
  uploadState: UploadProgressState;
  setCurrentClass: (value: ClassSummary | null) => void;
  loadDocuments: (showRefresh?: boolean) => Promise<void>;
  toggleSelection: (id: string) => void;
  selectAllDocuments: () => void;
  clearSelection: () => void;
  uploadPdfFiles: (files: { uri: string; name: string; mimeType?: string }[]) => Promise<void>;
  uploadLinkUrl: (url: string) => Promise<void>;
};

const emptyUploadState: UploadProgressState = {
  status: 'idle',
  visible: false,
  progress: 0,
  done: 0,
  total: 0,
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function createClientId() {
  return `mobile_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

export function DocumentWorkspaceProvider({ children }: PropsWithChildren) {
  const { t } = useLanguage();
  const [currentClass, setCurrentClassState] = useState<ClassSummary | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [uploadState, setUploadState] = useState<UploadProgressState>(emptyUploadState);

  const loadDocuments = useCallback(async (showRefresh = false) => {
    if (!currentClass?.id) {
      setDocuments([]);
      setSelectedIds([]);
      return;
    }

    if (showRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const result = await listDocuments(String(currentClass.id));
      const nextDocuments = result.files ?? [];
      setDocuments(nextDocuments);
      const nextIds = new Set(nextDocuments.map((item) => String(item.id)));
      setSelectedIds((current) => current.filter((id) => nextIds.has(id)));
    } catch (error) {
      Alert.alert(t('source.loadFailed'), error instanceof Error ? error.message : t('common.unknownError'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [currentClass?.id, t]);

  const setCurrentClass = useCallback((value: ClassSummary | null) => {
    setCurrentClassState(value);
    setDocuments([]);
    setSelectedIds([]);
    setUploadState(emptyUploadState);
  }, []);

  const toggleSelection = useCallback((id: string) => {
    setSelectedIds((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ));
  }, []);

  const selectAllDocuments = useCallback(() => {
    setSelectedIds(documents.map((document) => String(document.id)));
  }, [documents]);

  const clearSelection = useCallback(() => {
    setSelectedIds([]);
  }, []);

  const runTrackedUpload = useCallback(async (
    runner: (clientId: string) => Promise<void>,
  ) => {
    if (!currentClass?.id) {
      Alert.alert(t('common.error'), t('source.uploadNoClass'));
      return;
    }

    const clientId = createClientId();
    setUploadState({
      status: 'running',
      visible: true,
      progress: 0,
      done: 0,
      total: 0,
    });

    const unsubscribe = subscribeUploadProgress(clientId, {
      onProgress: (event) => {
        setUploadState((current) => {
          const done = typeof event.done === 'number' ? event.done : current.done;
          const total = typeof event.total === 'number' ? event.total : current.total;
          const progress = total > 0 ? Math.min(100, Math.floor((done / total) * 100)) : current.progress;
          return {
            ...current,
            status: 'running',
            visible: true,
            progress,
            done,
            total,
            currentFile: typeof event.currentFile === 'string' ? event.currentFile : current.currentFile,
            lastFileStatus: typeof event.lastFileStatus === 'string' ? event.lastFileStatus : current.lastFileStatus,
          };
        });
      },
      onFinished: (event) => {
        const summary = event.summary && typeof event.summary === 'object'
          ? event.summary as { total?: number; succeeded?: number; failed?: number }
          : undefined;
        const status = event.status === 'success' || event.status === 'partial' || event.status === 'failed'
          ? event.status
          : 'success';
        setUploadState({
          status,
          visible: true,
          progress: 100,
          done: summary?.total ?? 0,
          total: summary?.total ?? 0,
          summary,
          message: typeof event.message === 'string' ? event.message : undefined,
        });
      },
      onError: () => {
        setUploadState((current) => ({
          ...current,
          status: 'failed',
          visible: true,
          message: t('source.uploadFailed'),
        }));
      },
    });

    try {
      await runner(clientId);
      await loadDocuments();
    } catch (error) {
      setUploadState((current) => ({
        ...current,
        status: 'failed',
        visible: true,
        message: error instanceof Error ? error.message : t('common.unknownError'),
      }));
      throw error;
    } finally {
      unsubscribe();
    }
  }, [currentClass?.id, loadDocuments, t]);

  const uploadPdfFiles = useCallback(async (files: { uri: string; name: string; mimeType?: string }[]) => {
    if (!currentClass?.id || files.length === 0) {
      return;
    }
    await runTrackedUpload(async (clientId) => {
      await uploadMultiple(files, clientId, String(currentClass.id));
    });
  }, [currentClass?.id, runTrackedUpload]);

  const uploadLinkUrl = useCallback(async (url: string) => {
    if (!currentClass?.id) {
      return;
    }
    await runTrackedUpload(async (clientId) => {
      await uploadLink(url, clientId, String(currentClass.id));
    });
  }, [currentClass?.id, runTrackedUpload]);

  const value = useMemo(() => ({
    currentClass,
    documents,
    selectedIds,
    loading,
    refreshing,
    uploadState,
    setCurrentClass,
    loadDocuments,
    toggleSelection,
    selectAllDocuments,
    clearSelection,
    uploadPdfFiles,
    uploadLinkUrl,
  }), [
    clearSelection,
    currentClass,
    documents,
    loadDocuments,
    loading,
    refreshing,
    selectedIds,
    setCurrentClass,
    selectAllDocuments,
    toggleSelection,
    uploadLinkUrl,
    uploadPdfFiles,
    uploadState,
  ]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useDocumentWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error('useDocumentWorkspace must be used within DocumentWorkspaceProvider');
  }
  return context;
}
