import { Redirect, Tabs, router } from 'expo-router';
import React from 'react';
import { Pressable, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { useAuth } from '@/lib/auth-context';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { colors } from '@/lib/styles';
import { useLanguage } from '@/lib/i18n';

export default function WorkspaceLayout() {
  const { sessionToken } = useAuth();
  const { currentClass, setCurrentClass } = useDocumentWorkspace();
  const { t } = useLanguage();

  const goBackToClasses = () => {
    setCurrentClass(null);
    router.replace('/classes');
  };

  if (!sessionToken) {
    return <Redirect href="/login" />;
  }

  if (!currentClass) {
    return <Redirect href="/classes" />;
  }

  return (
    <Tabs
      screenOptions={{
        headerShown: true,
        tabBarHideOnKeyboard: false,
        tabBarShowLabel: true,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          height: 62,
          paddingBottom: 6,
          paddingTop: 6,
        },
        headerLeft: () => (
          <Pressable
            accessibilityRole="button"
            onPress={goBackToClasses}
            style={({ pressed }) => ({
              alignItems: 'center',
              flexDirection: 'row',
              gap: 4,
              marginLeft: 8,
              opacity: pressed ? 0.65 : 1,
              paddingHorizontal: 8,
              paddingVertical: 6,
            })}>
            <Ionicons color={colors.primary} name="chevron-back" size={20} />
            <Text style={{ color: colors.primary, fontSize: 14, fontWeight: '700' }}>
              {t('classes.title')}
            </Text>
          </Pressable>
        ),
      }}>
      <Tabs.Screen
        name="source"
        options={{
          title: t('source.title'),
          tabBarLabel: t('tabs.source'),
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              color={color}
              name={focused ? 'folder-open' : 'folder-open-outline'}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="chat"
        options={{
          title: t('chat.title'),
          tabBarLabel: t('tabs.chat'),
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              color={color}
              name={focused ? 'chatbubble' : 'chatbubble-outline'}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="studio"
        options={{
          title: 'Studio',
          tabBarLabel: 'Studio',
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons
              color={color}
              name={focused ? 'grid' : 'grid-outline'}
              size={size}
            />
          ),
        }}
      />
    </Tabs>
  );
}
