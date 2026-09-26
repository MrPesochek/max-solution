import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './api/queryClient';
import { SessionProvider, useSession } from './session/SessionContext';
import { AppRouter } from './router';
import { SplashScreen } from './screens/session/SplashScreen';
import { ReopenRequiredScreen } from './screens/session/ReopenRequiredScreen';
import { LoginScreen } from './screens/session/LoginScreen';
import { LinkInvalidScreen } from './screens/session/LinkInvalidScreen';

function Gate() {
  const { status } = useSession();

  if (status === 'loading') return <SplashScreen />;
  if (status === 'reopen_required') return <ReopenRequiredScreen />;
  if (status === 'link_invalid') return <LinkInvalidScreen />;
  if (status === 'demo_login' || status === 'login_error') return <LoginScreen />;

  return <AppRouter />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <Gate />
      </SessionProvider>
    </QueryClientProvider>
  );
}
