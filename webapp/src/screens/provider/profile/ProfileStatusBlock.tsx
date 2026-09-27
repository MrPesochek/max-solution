import { useState } from 'react';
import { strings } from '../../../strings/ru';
import {
  useSubmitVerificationInformation,
  useVerificationCases,
} from '../../../api/hooks/useVerification';
import type { ProviderProfile, VerificationDecision } from '../../../api/types';
import { actionErrorMessage } from '../../../components/actions/actionErrors';
import { Banner, Note, TextCard } from '../../../ui/blocks/Blocks';
import { List, ListRow, type RowMarker } from '../../../ui/List';
import { StatusHero } from '../../../ui/StatusHero';
import { Sheet } from '../../../ui/Sheet';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { TextAreaField } from '../../../ui/FormField';
import { shortDateTime } from '../../../ui/format';
import { useAppealProviderProfile } from '../../../api/hooks/useProviderProfile';

function dayMonth(iso: string): string {
  return shortDateTime(iso).split(',')[0]!;
}

const MARKER: Record<VerificationDecision, RowMarker> = {
  approved: 'ok',
  pending: 'w',
  needs_information: 'w',
  rejected: 'x',
  revoked: 'x',
};

function VerificationMarkers() {
  const cases = useVerificationCases();
  if (!cases.data || cases.data.length === 0) return null;
  return (
    <List aria-label={strings.provider.verificationTitle}>
      {cases.data.map((item) => (
        <ListRow
          key={item.id}
          marker={MARKER[item.decision]}
          title={strings.provider.verificationCaseSubject[item.check_kind] ?? item.check_kind}
          subtitle={item.decision_reason ?? strings.provider.verificationDecision[item.decision]}
        />
      ))}
    </List>
  );
}

function InformationAnswer() {
  const submitInfo = useSubmitVerificationInformation();
  const [note, setNote] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setError(null);
    try {
      await submitInfo.mutateAsync({ note: note.trim(), attachment_refs: [] });
      setNote('');
      setSent(true);
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <>
      <TextAreaField
        id="verification-answer"
        label={strings.provider.informationAnswerLabel}
        placeholder={strings.provider.informationAnswerPlaceholder}
        value={note}
        onChange={(value) => {
          setSent(false);
          setNote(value);
        }}
        rows={3}
      />
      <List>
        <ListRow
          title={strings.provider.informationSend}
          action="accent"
          disabled={!note.trim()}
          loading={submitInfo.isPending}
          onClick={() => void send()}
        />
        <ListRow
          title={strings.provider.verificationDocumentsRow}
          to="/provider/verification"
          chevron
        />
      </List>
      {sent && <Note role="status">{strings.provider.verificationSubmitted}</Note>}
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </>
  );
}

export function ProfileStatusBlock({
  profile,
  isAdmin,
}: {
  profile: ProviderProfile;
  isAdmin: boolean;
}) {
  const [details, setDetails] = useState(false);
  const [appeal, setAppeal] = useState(false);
  const status = profile.status;

  if (status === 'draft') {
    return (
      <>
        <StatusHero icon="+" tone="a" top={40} title={strings.provider.draftHeroTitle}>
          {strings.provider.statusWhatHappens.draft}
        </StatusHero>
        <Note>{strings.provider.beforeActiveNotice}</Note>
      </>
    );
  }

  if (status === 'pending_review') {
    return (
      <>
        <StatusHero icon="…" top={60} title={strings.provider.pendingHeroTitle}>
          {strings.provider.pendingHeroText(shortDateTime(profile.updated_at).split(',')[0]!)}
        </StatusHero>
        {isAdmin && <VerificationMarkers />}
      </>
    );
  }

  if (status === 'needs_information') {
    return (
      <>
        <Banner tone="y" title={strings.provider.needsInfoTitle}>
          {profile.status_reason ?? strings.provider.statusWhatHappens.needs_information}
        </Banner>
        {isAdmin ? (
          <InformationAnswer />
        ) : (
          <Note>{strings.provider.statusWhatToDo.needs_information}</Note>
        )}
      </>
    );
  }

  const title =
    status === 'suspended' ? strings.provider.suspendedTitle : strings.provider.rejectedTitle;
  const appealState = profile.appeal ?? null;
  const appealOpen = Boolean(appealState && !appealState.decision);
  return (
    <>
      <Banner tone="x" title={title}>
        {[
          status === 'suspended'
            ? strings.provider.suspendedText
            : strings.provider.statusWhatHappens[status],
          profile.status_reason && strings.provider.reasonText(profile.status_reason),
        ]
          .filter(Boolean)
          .join(' ')}
      </Banner>
      <Note>{strings.provider.keptNotice}</Note>
      <List>
        <ListRow
          title={strings.provider.decisionDetails}
          chevron
          expanded={details}
          onClick={() => setDetails((v) => !v)}
        />
        {appealState && <AppealStateRow appeal={appealState} />}
        {isAdmin && !appealOpen && (
          <ListRow
            title={appealState ? strings.provider.appealAgain : strings.provider.appealAction}
            action="accent"
            onClick={() => setAppeal(true)}
          />
        )}
      </List>
      {details && <TextCard>{strings.provider.statusWhatToDo[status]}</TextCard>}
      <AppealSheet open={appeal} onClose={() => setAppeal(false)} />
    </>
  );
}

function AppealStateRow({ appeal }: { appeal: NonNullable<ProviderProfile['appeal']> }) {
  const p = strings.provider;
  if (!appeal.decision) {
    return (
      <ListRow
        marker="w"
        title={p.appealPendingTitle}
        subtitle={p.appealPendingText(dayMonth(appeal.created_at))}
      />
    );
  }
  const upheld = appeal.decision !== 'rejected';
  return (
    <ListRow
      marker={upheld ? 'ok' : 'x'}
      title={upheld ? p.appealUpheldTitle : p.appealDeclinedTitle}
      subtitle={[appeal.decision_reason, appeal.resolved_at ? dayMonth(appeal.resolved_at) : null]
        .filter(Boolean)
        .join(' · ')}
    />
  );
}

function AppealSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const submit = useAppealProviderProfile();
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const p = strings.provider;

  const send = async () => {
    setError(null);
    try {
      await submit.mutateAsync({ text: text.trim() });
      setText('');
      onClose();
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <Sheet
      open={open}
      title={p.appealSheetTitle}
      description={p.appealSheetText}
      onClose={onClose}
      locked={submit.isPending}
      actions={
        <>
          <ActionButton
            loading={submit.isPending}
            disabled={!text.trim() || submit.isPending}
            onClick={() => void send()}
          >
            {p.appealSend}
          </ActionButton>
          <ActionButton kind="s" disabled={submit.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id="profile-appeal"
        label={p.appealTextLabel}
        placeholder={p.appealTextPlaceholder}
        value={text}
        onChange={setText}
        rows={4}
      />
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Sheet>
  );
}
