import { strings } from '../../strings/ru';
import { SectionCaption } from '../blocks/Blocks';
import { Segmented } from '../Segmented';
import { useThemePreference, type ThemePreference } from './themeContext';

const ITEMS: { id: ThemePreference; label: string }[] = [
  { id: 'system', label: strings.ui.theme.system },
  { id: 'light', label: strings.ui.theme.light },
  { id: 'dark', label: strings.ui.theme.dark },
];

export function ThemeSwitcher() {
  const { preference, setPreference, controlledByMax } = useThemePreference();
  if (controlledByMax) return null;
  return (
    <section aria-label={strings.ui.theme.caption}>
      <SectionCaption>{strings.ui.theme.caption}</SectionCaption>
      <Segmented
        items={ITEMS}
        value={preference}
        onChange={setPreference}
        label={strings.ui.theme.label}
      />
    </section>
  );
}
