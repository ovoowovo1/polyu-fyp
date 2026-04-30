import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const memoryStore = new Map<string, string>();

export async function getStoredValue(key: string) {
  if (Platform.OS === 'web') {
    return globalThis.localStorage?.getItem(key) ?? memoryStore.get(key) ?? null;
  }
  return SecureStore.getItemAsync(key);
}

export async function setStoredValue(key: string, value: string) {
  if (Platform.OS === 'web') {
    globalThis.localStorage?.setItem(key, value);
    memoryStore.set(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function deleteStoredValue(key: string) {
  if (Platform.OS === 'web') {
    globalThis.localStorage?.removeItem(key);
    memoryStore.delete(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}
