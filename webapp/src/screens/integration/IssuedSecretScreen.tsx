import { useState, type ReactNode } from 'react';
import { strings } from '../../strings/ru';
import { copyText } from '../../lib/clipboard';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { TextField } from '../../ui/FormField';
import { Sheet } from '../../ui/Sheet';

export function IssuedSecretScreen({
  id,
  title,
  onceTitle,
  onceText,
  label,
  value,
  copyLabel,
  onClose,
  children,
}: {
  id: string;
  title: string;
  onceTitle: string;
  onceText: string;
  label: string;
  value: string;
  copyLabel: string;
  onClose: () => void;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const copy = async () => {
    const ok = await copyText(value);
    setCopied(ok);
    setCopyFailed(!ok);
  };
  const requestClose = () => {
    if (copied) onClose();
    else setConfirmLeave(true);
  };

  return (
    <Screen
      title={title}
      back={requestClose}
      actions={
        <BottomActions>
          <ActionButton onClick={requestClose}>{strings.integration.issuedClose}</ActionButton>
        </BottomActions>
      }
    >
      <Banner tone="y" role="alert" title={onceTitle}>
        {onceText}
      </Banner>
      <TextField
        id={id}
        label={label}
        readOnly
        value={value}
        className="ui-field__control--mono"
        onFocus={(e) => e.target.select()}
      />
      <List>
        <ListRow
          title={copied ? strings.integration.copied : copyLabel}
          action="accent"
          onClick={() => void copy()}
        />
      </List>
      {copyFailed && (
        <Note tone="error" role="alert">
          {strings.integration.copyFailed}
        </Note>
      )}
      {children}
      <Sheet
        open={confirmLeave}
        role="alertdialog"
        title={strings.integration.leaveUncopiedTitle}
        description={strings.integration.leaveUncopiedText}
        onClose={() => setConfirmLeave(false)}
        actions={
          <>
            <ActionButton kind="d" onClick={onClose}>
              {strings.integration.leaveUncopiedConfirm}
            </ActionButton>
            <ActionButton kind="s" onClick={() => setConfirmLeave(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      />
    </Screen>
  );
}
