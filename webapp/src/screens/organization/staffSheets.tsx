import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useApproveMembership, useRevokeMembership } from '../../api/hooks/useMemberships';
import { useRevokeInvitation } from '../../api/hooks/useInvitations';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { shortDateTime } from '../../ui/format';
import { Sheet } from '../../ui/Sheet';
import { ActionButton } from '../../ui/layout/ActionButton';
import { useSession } from '../../session/SessionContext';
import { canEditMembershipLocations } from '../../lib/roles';
import type { Invitation, StaffMember } from '../../api/types';

function approveRows(member: StaffMember): KeyValueRow[] {
  const rows: KeyValueRow[] = [
    { label: strings.organization.approveNameInMax, value: member.user.display_name },
  ];
  if (member.expected_name) {
    rows.push({ label: strings.organization.approveExpectedName, value: member.expected_name });
  }
  if (member.accepted_at) {
    rows.push({
      label: strings.organization.approveAcceptedAt,
      value: shortDateTime(member.accepted_at),
    });
  }
  return rows;
}

export function ApproveSheet({
  member,
  onClose,
}: {
  member: StaffMember | null;
  onClose: () => void;
}) {
  const approve = useApproveMembership();
  const reject = useRevokeMembership();
  const [error, setError] = useState<string | null>(null);
  const busy = approve.isPending || reject.isPending;
  const close = () => {
    setError(null);
    onClose();
  };
  const handlers = {
    onSuccess: close,
    onError: (e: unknown) => setError(actionErrorMessage(e, strings.common.unknownError)),
  };
  return (
    <Sheet
      open={member !== null}
      role="alertdialog"
      title={member ? strings.organization.approveTitle(member.user.display_name) : undefined}
      description={strings.organization.approveText}
      onClose={close}
      locked={busy}
      actions={
        <>
          <ActionButton
            loading={approve.isPending}
            disabled={reject.isPending}
            onClick={() => {
              if (!member) return;
              setError(null);
              approve.mutate(member.id, handlers);
            }}
          >
            {strings.organization.approve}
          </ActionButton>
          {/* Отклонение заявки на вступление — тот же отзыв членства на сервере. */}
          <ActionButton
            kind="d"
            loading={reject.isPending}
            disabled={approve.isPending}
            onClick={() => {
              if (!member) return;
              setError(null);
              reject.mutate(member.id, handlers);
            }}
          >
            {strings.organization.reject}
          </ActionButton>
          <ActionButton kind="s" disabled={busy} onClick={close}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      {member && (
        <>
          <KeyValueRows rows={approveRows(member)} aria-label={strings.organization.approveCheck} />
          <Note>{strings.organization.approveCheck}</Note>
        </>
      )}
      {error && <Banner tone="x" role="alert" title={error} />}
    </Sheet>
  );
}

export function MemberSheet({
  member,
  subtitle,
  onClose,
}: {
  member: StaffMember | null;
  subtitle?: string;
  onClose: () => void;
}) {
  const { activeMembership } = useSession();
  const revoke = useRevokeMembership();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setConfirming(false);
    setError(null);
    onClose();
  };
  const name = member?.user.display_name ?? '';
  const canEditLocations =
    activeMembership !== null &&
    canEditMembershipLocations(activeMembership.role) &&
    member?.role === 'customer_employee';

  if (confirming) {
    return (
      <Sheet
        open={member !== null}
        role="alertdialog"
        title={strings.organization.memberRevokeTitle(name)}
        description={strings.organization.memberRevokeText}
        onClose={close}
        locked={revoke.isPending}
        actions={
          <>
            <ActionButton
              kind="d"
              loading={revoke.isPending}
              onClick={() => {
                if (!member) return;
                setError(null);
                revoke.mutate(member.id, {
                  onSuccess: close,
                  onError: (e) => setError(actionErrorMessage(e, strings.common.unknownError)),
                });
              }}
            >
              {strings.organization.memberRevoke}
            </ActionButton>
            <ActionButton kind="s" disabled={revoke.isPending} onClick={close}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        {error && <Banner tone="x" role="alert" title={error} />}
      </Sheet>
    );
  }

  return (
    <Sheet
      open={member !== null}
      title={name}
      description={subtitle}
      onClose={close}
      actions={
        <>
          {canEditLocations && member && (
            <ActionButton kind="s" to={`/organization/staff/${member.id}/locations`}>
              {strings.organization.editLocations}
            </ActionButton>
          )}
          <ActionButton kind="d" onClick={() => setConfirming(true)}>
            {strings.organization.memberRevoke}
          </ActionButton>
          <ActionButton kind="s" onClick={close}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    />
  );
}

export function RevokeSheet({
  invitation,
  onClose,
}: {
  invitation: Invitation | null;
  onClose: () => void;
}) {
  const revoke = useRevokeInvitation();
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setError(null);
    onClose();
  };
  return (
    <Sheet
      open={invitation !== null}
      role="alertdialog"
      title={strings.organization.inviteRevokeTitle}
      description={strings.organization.inviteRevokeText}
      onClose={close}
      locked={revoke.isPending}
      actions={
        <>
          <ActionButton
            kind="d"
            loading={revoke.isPending}
            onClick={() => {
              if (!invitation) return;
              setError(null);
              revoke.mutate(invitation.id, {
                onSuccess: close,
                onError: (e) => setError(actionErrorMessage(e, strings.common.unknownError)),
              });
            }}
          >
            {strings.common.revoke}
          </ActionButton>
          <ActionButton kind="s" disabled={revoke.isPending} onClick={close}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      {error && <Banner tone="x" role="alert" title={error} />}
    </Sheet>
  );
}
