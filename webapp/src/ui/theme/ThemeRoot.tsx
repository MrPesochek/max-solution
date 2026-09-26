import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { MaxUI } from '@maxhub/max-ui';
import { getColorScheme } from '../../max/bridge';
import {
  ThemeContext,
  readStoredPreference,
  storePreference,
  type ColorScheme,
  type ThemePreference,
} from './themeContext';

const DARK_QUERY = '(prefers-color-scheme: dark)';

function systemScheme(): ColorScheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light';
}

interface ThemeRootProps {
  colorScheme?: ColorScheme;
  platform?: 'ios' | 'android';
  children: ReactNode;
}

export function ThemeRoot({ colorScheme: initialMaxScheme, platform, children }: ThemeRootProps) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [colorScheme, setColorScheme] = useState<ColorScheme | undefined>(initialMaxScheme);
  useEffect(() => setColorScheme(initialMaxScheme), [initialMaxScheme]);
  const controlledByMax = Boolean(initialMaxScheme);
  useEffect(() => {
    if (!controlledByMax || typeof document === 'undefined') return;
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      const next = getColorScheme();
      if (next) setColorScheme(next);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [controlledByMax]);
  const [system, setSystem] = useState<ColorScheme>(systemScheme);

  const followsSystem = !colorScheme && preference === 'system';
  useEffect(() => {
    if (!followsSystem || typeof window === 'undefined' || !window.matchMedia) return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => setSystem(media.matches ? 'dark' : 'light');
    onChange();
    media.addEventListener?.('change', onChange);
    return () => media.removeEventListener?.('change', onChange);
  }, [followsSystem]);

  const scheme: ColorScheme = colorScheme ?? (preference === 'system' ? system : preference);

  useEffect(() => {
    document.documentElement.dataset.theme = scheme;
  }, [scheme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    storePreference(next);
  }, []);

  const value = useMemo(
    () => ({ scheme, preference, setPreference, controlledByMax }),
    [scheme, preference, setPreference, controlledByMax],
  );

  return (
    <ThemeContext.Provider value={value}>
      <MaxUI className="ui-root" resetBody colorScheme={scheme} platform={platform}>
        {children}
      </MaxUI>
    </ThemeContext.Provider>
  );
}
