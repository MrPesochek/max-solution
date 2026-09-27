import { strings } from '../../strings/ru';
import type { ApiKey } from '../../api/types';
import { Banner } from '../../ui/blocks/Blocks';

export function KeyWarnings({ apiKey }: { apiKey: ApiKey }) {
  const warnings = apiKey.warnings ?? [];
  if (warnings.length === 0) return null;
  return (
    <>
      {warnings.map((warning) => {
        const text = strings.integration.keyWarning[warning];
        return (
          <Banner key={warning} tone="y" title={text?.title ?? warning}>
            {text?.text}
          </Banner>
        );
      })}
    </>
  );
}
