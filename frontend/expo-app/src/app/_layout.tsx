import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router/stack';
import React from 'react';
import { useColorScheme } from 'react-native';

import { AuthProvider } from '@/lib/auth-context';
import { DocumentWorkspaceProvider } from '@/lib/document-workspace-context';
import { LanguageProvider } from '@/lib/i18n';

function RootStack() {
  return (
    <Stack
      screenOptions={{
        headerBackButtonDisplayMode: 'minimal',
        headerLargeTitle: false,
      }}>
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="login" options={{ headerShown: false }} />
      <Stack.Screen name="classes" options={{ headerShown: true }} />
      <Stack.Screen name="(workspace)" options={{ headerShown: false }} />
      <Stack.Screen name="source/[sourceId]" options={{ title: 'Source' }} />
      <Stack.Screen name="studio/quiz/[quizId]" options={{ title: 'Quiz' }} />
      <Stack.Screen name="studio/exam/[examId]" options={{ title: 'Exam' }} />
    </Stack>
  );
}

export default function RootLayout() {
  const colorScheme = useColorScheme();

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <LanguageProvider>
        <AuthProvider>
          <DocumentWorkspaceProvider>
            <RootStack />
          </DocumentWorkspaceProvider>
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}
