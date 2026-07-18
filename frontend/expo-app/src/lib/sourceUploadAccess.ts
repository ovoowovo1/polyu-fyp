import type { User } from '@/lib/types';

export function canUploadSources(user: User | null) {
  return user?.role === 'teacher';
}
