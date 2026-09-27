import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useOperatorProviderProfiles,
  useReinstateProvider,
  useSuspendProvider,
} from '../../api/hooks/useOperatorProviders';
import {
  useDecideModerationCase,
  useOperatorModerationCases,
} from '../../api/hooks/useOperatorReputation';
import type { ModerationCaseOperator, OperatorProviderProfile } from '../../api/operatorTypes';
import type { ProviderProfileStatus } from '../../api/types';
import { useConfirm } from '../../components/useConfirm';
import { formatDateTime } from '../../lib/datetime';
import { Banner, Note, SectionCaption, TextCard, type Tone } from '../../ui/blocks/Blocks';
import { Segmented } from '../../ui/Segmented';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { initials } from '../../ui/format';
import { OperatorScreen } from './OperatorScreen';

const STATUS_TONE: Record<ProviderProfileStatus, Tone> = {
  draft: 'w',
  pending_review: 'a',
  needs_information: 'y',
  active: 'ok',
  suspended: 'x',
  rejected: 'x',
};

function statusLabel(status: ProviderProfileStatus): string {
  return strings.provider.statusLabel[status] ?? status;
}

function ProfileSheet({
  profile,
  onClose,
}: {
  profile: OperatorProviderProfile;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const suspend = useSuspendProvider(profile.organization_id);
  const reinstate = useReinstateProvider(profile.organization_id);
  const { confirm, dialog } = useConfirm();

  const isActive = profile.status === 'active';
  const pending = suspend.isPending || reinstate.isPending;
  const actionLabel = isActive
    ? strings.operator.profileSuspendAction
    : strings.operator.profileReinstateAction;

  const handleSubmit = async () => {
    if (!reason.trim()) return;
    const ok = await confirm({
      title: `${actionLabel}?`,
      description: strings.operator.decisionConfirm,
      destructive: isActive,
    });
    if (!ok) return;
    setError(null);
    try {
      if (isActive) await suspend.mutateAsync({ reason: reason.trim() });
      else await reinstate.mutateAsync({ reason: reason.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.profileActionError);
    }
  };

  return (
    <Sheet
      open
      title={profile.name}
      description={statusLabel(profile.status)}
      onClose={onClose}
      locked={pending}
      actions={
        <>
          <ActionButton
            kind={isActive ? 'd' : 'p'}
            disabled={!reason.trim()}
            loading={pending}
            onClick={() => void handleSubmit()}
          >
            {actionLabel}
          </ActionButton>
          <ActionButton kind="s" disabled={pending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id={`reason-${profile.id}`}
        label={strings.operator.profileReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

type Tab = 'profiles' | 'appeals';
const APPEAL_STATUS = 'pending';

type AppealDecision = 'removed' | 'rejected';

function AppealSheet({ item, onClose }: { item: ModerationCaseOperator; onClose: () => void }) {
  const [decision, setDecision] = useState<AppealDecision>('removed');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const decide = useDecideModerationCase(item.id, 'provider_profile', APPEAL_STATUS);
  const { confirm, dialog } = useConfirm();
  const o = strings.operator;
  const text = typeof item.evidence.description === 'string' ? item.evidence.description : null;
  const filedStatus = item.evidence.profile_status_at_filing;
  const filedReason = item.evidence.status_reason_at_filing;

  const handleSubmit = async () => {
    if (!reason.trim()) return;
    const ok = await confirm({ title: o.decisionConfirm, confirmLabel: o.confirmYes });
    if (!ok) return;
    setError(null);
    try {
      await decide.mutateAsync({ decision, reason: reason.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : o.decisionError);
    }
  };

  return (
    <Sheet
      open
      title={o.appealSheetTitle(item.filer_organization_name ?? strings.common.notSpecified)}
      description={
        typeof filedStatus === 'string'
          ? o.appealFiledStatus(
              statusLabel(filedStatus as ProviderProfileStatus),
              typeof filedReason === 'string' ? filedReason : null,
            )
          : formatDateTime(item.created_at)
      }
      onClose={onClose}
      locked={decide.isPending}
      actions={
        <>
          <ActionButton
            kind={decision === 'rejected' ? 'd' : 'p'}
            disabled={!reason.trim()}
            loading={decide.isPending}
            onClick={() => void handleSubmit()}
          >
            {o.decisionSubmit}
          </ActionButton>
          <ActionButton kind="s" disabled={decide.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <SectionCaption>{o.appealTextCaption}</SectionCaption>
      <TextCard>{text ?? strings.common.notSpecified}</TextCard>
      <SectionCaption>{o.decisionCaption}</SectionCaption>
      <Segmented
        items={[
          { id: 'removed', label: o.appealUphold },
          { id: 'rejected', label: o.appealDecline },
        ]}
        value={decision}
        onChange={setDecision}
        label={o.decisionLabel}
      />
      <TextAreaField
        id={`appeal-reason-${item.id}`}
        label={o.appealReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      <Note>{o.appealReinstateNote}</Note>
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function ProviderProfilesScreen() {
  const [tab, setTab] = useState<Tab>('profiles');
  const profiles = useOperatorProviderProfiles();
  const appeals = useOperatorModerationCases('provider_profile', APPEAL_STATUS, 'appeal');
  const [openId, setOpenId] = useState<string | null>(null);
  const items = profiles.data ?? [];
  const appealItems = appeals.data ?? [];
  const open = tab === 'profiles' ? (items.find((item) => item.id === openId) ?? null) : null;
  const openAppeal = tab === 'appeals' ? (appealItems.find((item) => item.id === openId) ?? null) : null;
  const o = strings.operator;

  return (
    <OperatorScreen
      title={o.providerProfilesTitle}
      query={tab === 'profiles' ? profiles : appeals}
      empty={tab === 'profiles' ? items.length === 0 : appealItems.length === 0}
      emptyTitle={tab === 'appeals' ? o.appealsEmpty : undefined}
      tabPanel={{ idPrefix: 'operator-profiles', tab }}
      toolbar={
        <Segmented
          mode="tab"
          idPrefix="operator-profiles"
          label={o.profilesViewLabel}
          items={[
            { id: 'profiles', label: o.profilesTab },
            {
              id: 'appeals',
              label: appealItems.length > 0 ? `${o.appealsTab} · ${appealItems.length}` : o.appealsTab,
            },
          ]}
          value={tab}
          onChange={(next) => {
            setOpenId(null);
            setTab(next);
          }}
        />
      }
      overlay={
        (open && <ProfileSheet key={open.id} profile={open} onClose={() => setOpenId(null)} />) ||
        (openAppeal && <AppealSheet key={openAppeal.id} item={openAppeal} onClose={() => setOpenId(null)} />)
      }
    >
      {tab === 'profiles' ? (
        <List>
          {items.map((profile) => {
            const actionable = profile.status === 'active' || profile.status === 'suspended';
            return (
              <ListRow
                key={profile.id}
                title={profile.name}
                icon={initials(profile.name)}
                gradient="g"
                tag={{ label: statusLabel(profile.status), tone: STATUS_TONE[profile.status] ?? 'w' }}
                chevron={actionable}
                opensDialog={actionable}
                onClick={actionable ? () => setOpenId(profile.id) : undefined}
              />
            );
          })}
        </List>
      ) : (
        <List>
          {appealItems.map((item) => (
            <ListRow
              key={item.id}
              title={item.filer_organization_name ?? strings.common.notSpecified}
              subtitle={formatDateTime(item.created_at)}
              icon={initials(item.filer_organization_name ?? '?')}
              gradient="g"
              tag={{ label: o.appealTag, tone: 'y' }}
              chevron
              opensDialog
              onClick={() => setOpenId(item.id)}
            />
          ))}
        </List>
      )}
    </OperatorScreen>
  );
}
