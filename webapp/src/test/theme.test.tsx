import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ThemeRoot } from '../ui/theme/ThemeRoot';
import { ThemeSwitcher } from '../ui/theme/ThemeSwitcher';
import { THEME_STORAGE_KEY } from '../ui/theme/themeContext';

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe('тема оформления', () => {
  it('вне MAX светлая по умолчанию; выбор сохраняется и ставит data-theme', async () => {
    const user = userEvent.setup();
    render(
      <ThemeRoot>
        <ThemeSwitcher />
      </ThemeRoot>,
    );
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(screen.getByRole('radio', { name: 'Светлая' })).toHaveAttribute('aria-checked', 'true');

    await user.click(screen.getByRole('radio', { name: 'Тёмная' }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('сохранённый выбор применяется при запуске', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    render(
      <ThemeRoot>
        <ThemeSwitcher />
      </ThemeRoot>,
    );
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('в MAX тема из bridge, переключателя нет', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light');
    render(
      <ThemeRoot colorScheme="dark">
        <ThemeSwitcher />
      </ThemeRoot>,
    );
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.queryByRole('radiogroup', { name: 'Тема' })).not.toBeInTheDocument();
  });
});
