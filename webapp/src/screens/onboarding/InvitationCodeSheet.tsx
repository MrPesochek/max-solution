import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { Sheet } from '../../ui/Sheet';
import { TextField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { extractInvitationToken } from './invitationToken';

export function InvitationCodeSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [value, setValue] = useState('');

  const submit = () => {
    const token = extractInvitationToken(value);
    if (!token) return;
    navigate(`/invitations/accept?token=${encodeURIComponent(token)}`);
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={strings.onboarding.invitationTitle}
      description={strings.onboarding.invitationNote}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <TextField
          id="invitation-input"
          label={strings.onboarding.invitationLinkLabel}
          value={value}
          onChange={setValue}
          autoFocus
          autoCapitalize="none"
          autoCorrect="off"
        />
        <div className="ui-pad">
          <ActionButton type="submit" disabled={!value.trim()}>
            {strings.onboarding.openInvitation}
          </ActionButton>
        </div>
      </form>
    </Sheet>
  );
}
