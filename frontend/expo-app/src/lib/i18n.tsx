import React, { createContext, PropsWithChildren, useCallback, useMemo, useState } from 'react';

type Language = 'zh-TW' | 'en';
type Params = Record<string, string | number>;

const messages = {
  'zh-TW': {
    'common.error': '錯誤',
    'common.id': 'ID',
    'common.logout': '登出',
    'common.cancel': '取消',
    'common.save': '儲存',
    'common.upload': '上傳',
    'common.unknownError': '發生未知錯誤',
    'login.student': '學生',
    'login.teacher': '教師',
    'login.studentTitle': '學生登入',
    'login.teacherTitle': '教師登入',
    'login.subtitle': '登入後選擇班級、閱讀來源文件，並向 RAG 助手提問。',
    'login.required': '請輸入電子郵件和密碼。',
    'login.failed': '登入失敗',
    'login.email': 'Email',
    'login.password': '密碼',
    'login.studentEmail': '學生 Email',
    'login.teacherEmail': '教師 Email',
    'login.passwordPlaceholder': '請輸入密碼',
    'login.submit': '登入',
    'classes.title': '我的班級',
    'classes.user': '使用者',
    'classes.search': '搜尋班級',
    'classes.empty': '沒有班級',
    'classes.emptyHint': '教師建立班級或邀請學生後，班級會顯示在這裡。',
    'classes.loadFailed': '載入班級失敗',
    'classes.students': '{{count}} 位學生',
    'classes.openSource': '開啟來源',
    'workspace.classRequired': '請先在 Classes 選擇班級。',
    'workspace.noClassSelected': '尚未選擇班級',
    'workspace.selectedClass': '目前班級',
    'tabs.classes': 'Classes',
    'tabs.source': 'Source',
    'tabs.chat': 'Chat',
    'source.title': '來源文件',
    'source.selected': '已選 {{count}} 份',
    'source.selectAll': 'Select all sources',
    'source.clearAll': 'Clear selection',
    'source.empty': '沒有文件',
    'source.emptyHint': '先上傳 PDF 或連結，再選擇來源作為聊天上下文。',
    'source.loadFailed': '載入文件失敗',
    'source.ready': 'Ready',
    'source.uploadPdf': 'Upload PDF',
    'source.uploadLink': 'Upload Link',
    'source.pickPdfFailed': '選取 PDF 失敗',
    'source.uploadFailed': '上傳失敗',
    'source.uploadNoClass': '請先選擇班級再上傳文件。',
    'source.linkTitle': 'Upload Link',
    'source.linkPlaceholder': 'https://example.com/article',
    'source.linkRequired': '請輸入有效連結。',
    'source.uploadProgress': '上傳進度',
    'source.uploadFinishedSuccess': '上傳完成',
    'source.uploadFinishedPartial': '部分完成',
    'source.uploadFinishedFailed': '上傳失敗',
    'source.progressSummary': '{{done}} / {{total}} 已完成',
    'source.progressCurrentFile': '目前文件: {{name}}',
    'source.progressStatus': '狀態: {{status}}',
    'source.progressResult': '成功 {{succeeded}} / 失敗 {{failed}}',
    'source.reader.title': '來源閱讀器',
    'source.reader.loadFailed': '載入來源內容失敗',
    'source.reader.content': '內容',
    'source.reader.noContent': '這個來源沒有可顯示的內容。',
    'source.reader.status': '狀態: {{status}}',
    'source.reader.focused': '引用段落',
    'chat.title': 'Chat',
    'chat.welcomeNoDocuments': '此班級目前沒有文件，請先上傳文件再提問。',
    'chat.welcomeNoSelection': '目前有 {{count}} 份文件，請先在 Source 選擇至少一份來源。',
    'chat.welcomeSelected': '已選 {{selected}} / {{count}} 份文件作為上下文。',
    'chat.placeholder': '輸入問題...',
    'chat.send': '送出',
    'chat.clear': '清除',
    'chat.thinking': '正在思考...',
    'chat.progress': '正在查找相關資料...',
    'chat.selectDocumentTitle': '請先選擇文件',
    'chat.selectDocumentMessage': '請至少選擇一份來源，再向助理提問。',
    'chat.selectDocumentHint': '請先選擇至少一份來源。',
    'chat.goToSource': '前往 Source',
    'chat.citationPreviewTitle': '引用預覽',
    'chat.citationPreviewMissing': '找不到這則引用對應的段落。',
    'chat.citationPreviewUnavailable': '這則引用目前無法開啟預覽。',
    'chat.citationSource': '來源：{{source}}',
    'chat.citationPage': '頁數：{{page}}',
    'chat.openFullSource': '開啟完整來源',
  },
  en: {
    'common.error': 'Error',
    'common.id': 'ID',
    'common.logout': 'Logout',
    'common.cancel': 'Cancel',
    'common.save': 'Save',
    'common.upload': 'Upload',
    'common.unknownError': 'An unknown error occurred',
    'login.student': 'Student',
    'login.teacher': 'Teacher',
    'login.studentTitle': 'Student Login',
    'login.teacherTitle': 'Teacher Login',
    'login.subtitle': 'Sign in, choose a class, read sources, and ask the RAG assistant.',
    'login.required': 'Please enter your email and password.',
    'login.failed': 'Login failed',
    'login.email': 'Email',
    'login.password': 'Password',
    'login.studentEmail': 'Student email',
    'login.teacherEmail': 'Teacher email',
    'login.passwordPlaceholder': 'Enter password',
    'login.submit': 'Login',
    'classes.title': 'My Classes',
    'classes.user': 'User',
    'classes.search': 'Search classes',
    'classes.empty': 'No classes',
    'classes.emptyHint': 'Classes appear after a teacher creates one or invites students.',
    'classes.loadFailed': 'Failed to load classes',
    'classes.students': '{{count}} students',
    'classes.openSource': 'Open Source',
    'workspace.classRequired': 'Select a class in Classes first.',
    'workspace.noClassSelected': 'No class selected',
    'workspace.selectedClass': 'Current class',
    'tabs.classes': 'Classes',
    'tabs.source': 'Source',
    'tabs.chat': 'Chat',
    'source.title': 'Sources',
    'source.selected': '{{count}} selected',
    'source.selectAll': 'Select all sources',
    'source.clearAll': 'Clear selection',
    'source.empty': 'No documents',
    'source.emptyHint': 'Upload PDFs or links, then select sources for chat context.',
    'source.loadFailed': 'Failed to load documents',
    'source.ready': 'Ready',
    'source.uploadPdf': 'Upload PDF',
    'source.uploadLink': 'Upload Link',
    'source.pickPdfFailed': 'Failed to pick PDF files',
    'source.uploadFailed': 'Upload failed',
    'source.uploadNoClass': 'Select a class before uploading files.',
    'source.linkTitle': 'Upload Link',
    'source.linkPlaceholder': 'https://example.com/article',
    'source.linkRequired': 'Enter a valid link.',
    'source.uploadProgress': 'Upload progress',
    'source.uploadFinishedSuccess': 'Upload completed',
    'source.uploadFinishedPartial': 'Upload partially completed',
    'source.uploadFinishedFailed': 'Upload failed',
    'source.progressSummary': '{{done}} / {{total}} completed',
    'source.progressCurrentFile': 'Current file: {{name}}',
    'source.progressStatus': 'Status: {{status}}',
    'source.progressResult': 'Succeeded {{succeeded}} / Failed {{failed}}',
    'source.reader.title': 'Source Reader',
    'source.reader.loadFailed': 'Failed to load source content',
    'source.reader.content': 'Content',
    'source.reader.noContent': 'No content was returned for this source.',
    'source.reader.status': 'Status: {{status}}',
    'source.reader.focused': 'Cited paragraph',
    'chat.title': 'Chat',
    'chat.welcomeNoDocuments': 'This class has no documents yet. Upload documents before asking questions.',
    'chat.welcomeNoSelection': '{{count}} documents available. Select at least one source in Source first.',
    'chat.welcomeSelected': '{{selected}} / {{count}} documents selected as context.',
    'chat.placeholder': 'Ask a question...',
    'chat.send': 'Send',
    'chat.clear': 'Clear',
    'chat.thinking': 'Thinking...',
    'chat.progress': 'Searching selected sources...',
    'chat.selectDocumentTitle': 'Select a document first',
    'chat.selectDocumentMessage': 'Select at least one source before asking the assistant.',
    'chat.selectDocumentHint': 'Select at least one source before asking.',
    'chat.goToSource': 'Go to Source',
    'chat.citationPreviewTitle': 'Citation preview',
    'chat.citationPreviewMissing': 'The cited paragraph could not be found.',
    'chat.citationPreviewUnavailable': 'This citation is not available for preview yet.',
    'chat.citationSource': 'Source: {{source}}',
    'chat.citationPage': 'Page: {{page}}',
    'chat.openFullSource': 'Open full source',
  },
} as const;

type MessageKey = keyof typeof messages.en;

type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: MessageKey, params?: Params) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: PropsWithChildren) {
  const [language, setLanguage] = useState<Language>('zh-TW');

  const t = useCallback((key: MessageKey, params: Params = {}) => {
    let value: string = messages[language][key] || messages.en[key] || key;
    Object.entries(params).forEach(([paramKey, paramValue]) => {
      value = value.replaceAll(`{{${paramKey}}}`, String(paramValue));
    });
    return value;
  }, [language]);

  const value = useMemo(() => ({ language, setLanguage, t }), [language, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = React.use(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within LanguageProvider');
  }
  return context;
}
