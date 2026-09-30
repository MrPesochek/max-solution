import { createContext, useContext } from 'react';

export type ColorScheme = 'light' | 'dark';
export type ThemePreference = 'system' | 'light' | 'dark';

export const THEME_STORAGE_KEY = 'max-repair.theme';

export interface ThemeContextValue {
  scheme: ColorScheme;
  preference: ThemePreference;
  setPreference: (next: ThemePreference) => void;
  controlledByMax: boolean;
}

export const ThemeContext = createContext<ThemeContextValue>({
  scheme: 'light',
  preference: 'light',
  setPreference: () => {},
  controlledByMax: false,
});

export function useThemePreference(): ThemeContextValue {
  return useContext(ThemeContext);
}

function isPreference(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark';
}

export function readStoredPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isPreference(value) ? value : 'light';
  } catch {
    return 'light';
  }
}

export function storePreference(value: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, value);
  } catch {
  }
}
