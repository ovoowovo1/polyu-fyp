import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { login } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { useLanguage } from '@/lib/i18n';
import { colors, commonStyles } from '@/lib/styles';
import type { LoginRole } from '@/lib/types';

export default function LoginScreen() {
  const { setSession } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const [role, setRole] = useState<LoginRole>('student');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email.trim() || !password.trim()) {
      Alert.alert(t('common.error'), t('login.required'));
      return;
    }

    setLoading(true);
    try {
      const result = await login(email.trim(), password, role);
      await setSession(result.session_token, result.user);
      router.replace('/classes');
    } catch (error) {
      Alert.alert(t('login.failed'), error instanceof Error ? error.message : t('common.unknownError'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView contentInsetAdjustmentBehavior="automatic" contentContainerStyle={commonStyles.screen}>
        <View style={{ gap: 10 }}>
          <Text selectable style={commonStyles.eyebrow}>
            PolyU FYP
          </Text>
          <Text selectable style={commonStyles.title}>
            {role === 'student' ? t('login.studentTitle') : t('login.teacherTitle')}
          </Text>
          <Text selectable style={commonStyles.subtitle}>
            {t('login.subtitle')}
          </Text>
        </View>

        <View style={commonStyles.segmented}>
          {(['student', 'teacher'] as const).map((nextRole) => (
            <Pressable
              key={nextRole}
              accessibilityRole="button"
              onPress={() => setRole(nextRole)}
              style={[commonStyles.segment, role === nextRole && commonStyles.segmentActive]}>
              <Text style={[commonStyles.segmentText, role === nextRole && commonStyles.segmentTextActive]}>
                {nextRole === 'student' ? t('login.student') : t('login.teacher')}
              </Text>
            </Pressable>
          ))}
        </View>

        <View style={commonStyles.card}>
          <Text selectable style={commonStyles.label}>
            {t('login.email')}
          </Text>
          <TextInput
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            onChangeText={setEmail}
            placeholder={role === 'student' ? t('login.studentEmail') : t('login.teacherEmail')}
            style={commonStyles.input}
            value={email}
          />

          <Text selectable style={commonStyles.label}>
            {t('login.password')}
          </Text>
          <TextInput
            autoCapitalize="none"
            onChangeText={setPassword}
            placeholder={t('login.passwordPlaceholder')}
            secureTextEntry
            style={commonStyles.input}
            value={password}
          />

          <Pressable
            accessibilityRole="button"
            disabled={loading}
            onPress={submit}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              (pressed || loading) && commonStyles.pressed,
            ]}>
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={commonStyles.primaryButtonText}>{t('login.submit')}</Text>
            )}
          </Pressable>
        </View>

        <View style={commonStyles.segmented}>
          {(['zh-TW', 'en'] as const).map((nextLanguage) => (
            <Pressable
              key={nextLanguage}
              accessibilityRole="button"
              onPress={() => setLanguage(nextLanguage)}
              style={[commonStyles.segment, language === nextLanguage && commonStyles.segmentActive]}>
              <Text
                style={[
                  commonStyles.segmentText,
                  language === nextLanguage && commonStyles.segmentTextActive,
                ]}>
                {nextLanguage === 'zh-TW' ? '中文' : 'EN'}
              </Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
