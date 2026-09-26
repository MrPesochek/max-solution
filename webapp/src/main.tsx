import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@maxhub/max-ui/dist/styles.css';
import '@fontsource/onest/400.css';
import '@fontsource/onest/500.css';
import '@fontsource/onest/600.css';
import '@fontsource/onest/700.css';
import '@fontsource/onest/800.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import { App } from './App';
import {
  loadMaxBridge,
  onBridgeReady,
  getStartParam,
  notifyReady,
  getColorScheme,
  getPlatform,
} from './max/bridge';
import { parseStartParam, startParamToPath } from './max/startParam';
import { captureLoginLinkToken } from './session/loginLink';
import { ThemeRoot } from './ui/theme/ThemeRoot';
import './styles/app.css';
import './ui/tokens.css';
import './ui/ui.css';

function applyInitialRoute(): void {
  if (window.location.hash && window.location.hash !== '#/') return;
  const path = startParamToPath(parseStartParam(getStartParam()));
  if (path) window.location.hash = `#${path}`;
}

async function startMocksIfNeeded(): Promise<void> {
  if (import.meta.env.VITE_USE_MOCKS !== 'true') return;
  const { worker } = await import('./mocks/browser');
  await worker.start({ onUnhandledRequest: 'bypass' });
}

async function bootstrap(): Promise<void> {
  captureLoginLinkToken();
  await startMocksIfNeeded();
  await loadMaxBridge();
  applyInitialRoute();
  onBridgeReady(() => {
    applyInitialRoute();
    notifyReady();
  });

  const rootElement = document.getElementById('root');
  if (!rootElement) throw new Error('Не найден #root');

  const colorScheme = getColorScheme() ?? undefined;
  const platform = getPlatform() ?? undefined;

  createRoot(rootElement).render(
    <StrictMode>
      <ThemeRoot colorScheme={colorScheme} platform={platform}>
        <App />
      </ThemeRoot>
    </StrictMode>,
  );

  notifyReady();
}

void bootstrap();
