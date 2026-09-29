import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadMaxBridge, resetMaxBridgeForTests } from '../max/bridge';
import { server } from '../mocks/server';
import { findHomeScreen, loginAsDemo, renderApp } from './testUtils';

const BRIDGE_URL = 'https://st.max.test/js/max-web-app.js';
const INIT_DATA = 'demo:customer_manager';

function bridgeScripts(): HTMLScriptElement[] {
  return [...document.head.querySelectorAll<HTMLScriptElement>(`script[src="${BRIDGE_URL}"]`)];
}

function bridgeScript(): HTMLScriptElement | null {
  const scripts = bridgeScripts();
  return scripts.length === 1 ? scripts[0]! : null;
}

function finishBridgeLoad(script: HTMLScriptElement) {
  window.WebApp = { initData: INIT_DATA };
  script.dispatchEvent(new Event('load'));
}

function countAuthCalls(): { count: number } {
  const counter = { count: 0 };
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/auth/max'))
      counter.count += 1;
  });
  return counter;
}

async function bootWithSlowBridge(): Promise<HTMLScriptElement> {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  const loaded = loadMaxBridge();
  await vi.advanceTimersByTimeAsync(5000);
  expect(await loaded).toBe(false);
  vi.useRealTimers();
  const script = bridgeScript();
  expect(script).not.toBeNull();
  return script!;
}

beforeEach(() => {
  resetMaxBridgeForTests();
  vi.stubEnv('VITE_MAX_BRIDGE_URL', BRIDGE_URL);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  resetMaxBridgeForTests();
  bridgeScripts().forEach((script) => script.remove());
});

describe('bridge MAX загрузился после таймаута', () => {
  it('скрипт пришёл через 5 с — вход по initData запускается сам', async () => {
    vi.stubEnv('VITE_DEMO_LOGIN', 'false');
    const calls = countAuthCalls();
    const script = await bootWithSlowBridge();
    renderApp();
    expect(await screen.findByText('Откройте приложение в MAX')).toBeInTheDocument();
    expect(calls.count).toBe(0);

    act(() => finishBridgeLoad(script));
    await findHomeScreen();
    expect(calls.count).toBe(1);
  });

  it('в демо-сборке поздний bridge тоже входит через MAX, а не оставляет демо-форму', async () => {
    const script = await bootWithSlowBridge();
    renderApp();
    expect(await screen.findByLabelText('Идентификатор демо-пользователя')).toBeInTheDocument();

    act(() => finishBridgeLoad(script));
    await findHomeScreen();
  });

  it('bridge так и не появился — «Откройте из MAX» с кнопкой «Повторить»; повтор без bridge оставляет экран', async () => {
    vi.stubEnv('VITE_DEMO_LOGIN', 'false');
    vi.stubEnv('VITE_MAX_BRIDGE_URL', '');
    const calls = countAuthCalls();
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText('Откройте приложение в MAX')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Откройте приложение в MAX')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
    expect(calls.count).toBe(0);
  });

  it('«Повторить» подгружает bridge заново и входит', async () => {
    vi.stubEnv('VITE_DEMO_LOGIN', 'false');
    const first = await bootWithSlowBridge();
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole('button', { name: 'Повторить' }));
    const retried = bridgeScript();
    expect(retried).not.toBeNull();
    expect(retried).not.toBe(first);
    expect(first.isConnected).toBe(false);

    act(() => finishBridgeLoad(retried!));
    await findHomeScreen();
  });

  it('пользователь уже вошёл — поздний bridge второй вход не запускает', async () => {
    const calls = countAuthCalls();
    const script = await bootWithSlowBridge();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    act(() => finishBridgeLoad(script));
    await findHomeScreen();
    expect(calls.count).toBe(0);
  });
});
