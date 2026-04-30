import { Redirect } from 'expo-router';

import { useAuth } from '@/lib/auth-context';
import { LoadingScreen } from '@/components/loading-screen';

export default function IndexScreen() {
  const { bootstrapping, sessionToken } = useAuth();

  if (bootstrapping) {
    return <LoadingScreen />;
  }

  return <Redirect href={sessionToken ? '/classes' : '/login'} />;
}
