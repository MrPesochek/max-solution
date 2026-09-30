import { useState } from 'react';
import { strings } from '../strings/ru';
import { haptics, openExternalLink } from '../max/bridge';
import { TextField } from '../ui/FormField';
import { ActionButton } from '../ui/layout/ActionButton';

export function LinkRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      haptics.notification('success');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
    }
  };
  return (
    <div className="link-row">
      <TextField readOnly label={label} value={value} onFocus={(e) => e.target.select()} />
      <div className="link-row__actions">
        <ActionButton kind="s" compact onClick={() => void handleCopy()}>
          {copied ? strings.common.copied : strings.common.copy}
        </ActionButton>
        <ActionButton kind="g" compact onClick={() => openExternalLink(value)}>
          {strings.common.open}
        </ActionButton>
      </div>
    </div>
  );
}
