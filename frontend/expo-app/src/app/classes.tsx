import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  Text,
  TextInput,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { listMyClasses, listMyEnrolledClasses } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { useDocumentWorkspace } from '@/lib/document-workspace-context';
import { useLanguage } from '@/lib/i18n';
import { colors, commonStyles } from '@/lib/styles';
import type { ClassSummary } from '@/lib/types';

export default function ClassesScreen() {
  const { logout, user } = useAuth();
  const { setCurrentClass } = useDocumentWorkspace();
  const { t } = useLanguage();
  const [classes, setClasses] = useState<ClassSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');

  const loadClasses = useCallback(async (showRefresh = false) => {
    if (showRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const response = user?.role === 'teacher' ? await listMyClasses() : await listMyEnrolledClasses();
      setClasses(response.classes ?? []);
    } catch (error) {
      Alert.alert(t('classes.loadFailed'), error instanceof Error ? error.message : t('common.unknownError'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [t, user?.role]);

  useEffect(() => {
    void loadClasses();
  }, [loadClasses]);

  const filtered = classes.filter((item) =>
    item.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const openClass = (item: ClassSummary) => {
    setCurrentClass(item);
    router.replace('/source');
  };

  return (
    <View style={commonStyles.fullScreen}>
      <View style={commonStyles.toolbar}>
        <View style={{ flex: 1 }}>
          <Text selectable style={commonStyles.toolbarTitle}>
            {user?.full_name || user?.email || t('classes.user')}
          </Text>
          <Text selectable style={commonStyles.muted}>
            {user?.role === 'teacher' ? t('login.teacher') : t('login.student')}
          </Text>
        </View>
        <Pressable accessibilityRole="button" onPress={handleLogout} style={commonStyles.secondaryButton}>
          <Text style={commonStyles.secondaryButtonText}>{t('common.logout')}</Text>
        </Pressable>
      </View>

      <FlatList
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={commonStyles.listContent}
        data={filtered}
        keyExtractor={(item) => String(item.id)}
        ListHeaderComponent={(
          <View style={{ gap: 10 }}>
            <TextInput
              onChangeText={setSearch}
              placeholder={t('classes.search')}
              style={commonStyles.input}
              value={search}
            />
            {loading && <ActivityIndicator color={colors.primary} />}
          </View>
        )}
        ListEmptyComponent={!loading ? (
          <View style={commonStyles.emptyBox}>
            <Text selectable style={commonStyles.emptyTitle}>{t('classes.empty')}</Text>
            <Text selectable style={commonStyles.muted}>{t('classes.emptyHint')}</Text>
          </View>
        ) : null}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadClasses(true)} />}
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            onPress={() => openClass(item)}
            style={({ pressed }) => [commonStyles.card, pressed && commonStyles.pressed]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View style={commonStyles.avatar}>
                <Text style={commonStyles.avatarText}>{item.name.slice(0, 1).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1, gap: 4 }}>
                <Text selectable numberOfLines={1} style={commonStyles.itemTitle}>
                  {item.name}
                </Text>
                <Text selectable numberOfLines={1} style={commonStyles.muted}>
                  {t('common.id')}: {item.id}
                </Text>
              </View>
              <Text style={{ color: colors.primary, fontSize: 22 }}>{'>'}</Text>
            </View>
            <Text selectable style={commonStyles.muted}>
              {t('classes.students', { count: item.student_count ?? 0 })}
            </Text>
          </Pressable>
        )}
      />
    </View>
  );
}
