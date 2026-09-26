import { useEffect, useRef, useState } from 'react';
import { strings } from '../../strings/ru';
import { haptics } from '../../max/bridge';
import { copyText } from '../../lib/clipboard';
import { ListRow } from '../../ui/List';
import { TextField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';

function useCopy(value: string) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const copy = async (): Promise<boolean> => {
    const ok = await copyText(value);
    if (!ok) {
      haptics.notification('error');
      setFailed(true);
      return false;
    }
    haptics.notification('success');
    setFailed(false);
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
    return true;
  };
  return { copied, failed, copy };
}

function ManualCopyField({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <TextField
      id={id}
      label={label}
      readOnly
      value={value}
      error={strings.common.copyFailed}
      className="ui-field__control--mono"
      onFocus={(event) => event.target.select()}
    />
  );
}

export function InviteCopyRow({ label, value }: { label: string; value: string }) {
  const { copied, failed, copy } = useCopy(value);
  const fieldId = `invite-link-${label.length}-${value.length}`;
  return (
    <>
      <ListRow
        title={label}
        action="accent"
        value={copied ? strings.common.copied : undefined}
        valueTone="secondary"
        onClick={() => void copy()}
      />
      {failed && <ManualCopyField id={fieldId} label={label} value={value} />}
    </>
  );
}

export function InviteShareButton({ link }: { link: string }) {
  const { copied, failed, copy } = useCopy(link);
  const share = async () => {
    if (typeof navigator.share === 'function') {
      try {
        await navigator.share({ text: strings.organization.inviteShareText, url: link });
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
      }
    }
    await copy();
  };
  return (
    <>
      {failed && <ManualCopyField id="invite-share-link" label={strings.organization.inviteSend} value={link} />}
      <ActionButton onClick={() => void share()}>
        {copied ? strings.organization.inviteCopiedForChat : strings.organization.inviteSend}
      </ActionButton>
    </>
  );
}
