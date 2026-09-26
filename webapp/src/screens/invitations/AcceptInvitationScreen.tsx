import { useState, type ReactNode } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useAcceptInvitation, useInvitationPreview } from '../../api/hooks/useInvitations';
import { ApiError } from '../../api/errors';
import { useSession } from '../../session/SessionContext';
import type { InvitationPreview, InvitationState } from '../../api/types';
import { Banner, PageTitle } from '../../ui/blocks/Blocks';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { SkeletonBlock, SkeletonRows } from '../../ui/Skeleton';
import type { IllustrationName } from '../../ui/illustrations';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { shortDateTime } from '../../ui/format';
import { ErrorState } from '../../components/states/ErrorState';
import { isInvalidInvitationError } from './invitationErrors';
import { StandaloneScreen } from '../onboarding/StandaloneScreen';

type Outcome = 'joined' | 'awaiting' | 'rejected' | 'expired';

function inactiveScene(
  state: InvitationState | 'unknown',
  expiresAt: string | null,
): { illustration: IllustrationName; title: string; text: string } {
  switch (state) {
    case 'expired':
      return {
        illustration: 'status-waiting',
        title: strings.invitationAccept.expiredTitle,
        text: expiresAt
          ? strings.invitationAccept.expiredUntil(shortDateTime(expiresAt))
          : strings.invitationAccept.expiredText,
      };
    case 'revoked':
      return {
        illustration: 'status-cancel',
        title: strings.invitationAccept.revokedTitle,
        text: strings.invitationAccept.revokedText,
      };
    case 'used':
    case 'declined':
      return {
        illustration: 'status-cancel',
        title: strings.invitationAccept.usedTitle,
        text: strings.invitationAccept.usedText,
      };
    default:
      return {
        illustration: 'status-cancel',
        title: strings.invitationAccept.invalidTitle,
        text: strings.invitationAccept.invalidText,
      };
  }
}

function detailRows(invitation: InvitationPreview): KeyValueRow[] {
  const rows: KeyValueRow[] = [
    { label: strings.invitationAccept.organization, value: invitation.organization_name ?? '' },
    {
      label: strings.invitationAccept.role,
      value: invitation.role
        ? strings.home.roleShort[invitation.role]
        : strings.common.notSpecified,
    },
  ];
  if (invitation.location_names.length > 0) {
    rows.push({
      label:
        invitation.location_names.length === 1
          ? strings.invitationAccept.location
          : strings.invitationAccept.locations,
      value: invitation.location_names.join(', '),
    });
  }
  const inviter = invitation.inviter_name?.trim();
  if (inviter) {
    rows.push({ label: strings.invitationAccept.invitedBy, value: inviter });
  }
  if (invitation.expires_at) {
    rows.push({
      label: strings.invitationAccept.expiresAt,
      value: shortDateTime(invitation.expires_at),
    });
  }
  return rows;
}

export function AcceptInvitationScreen() {
  const [searchParams] = useSearchParams();
  const [token] = useState(() => searchParams.get('token'));
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshMemberships, activateMembership } = useSession();
  const preview = useInvitationPreview(token);
  const acceptInvitation = useAcceptInvitation();
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const leave = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate('/organizations', { replace: true });
  };

  const frame = (body: ReactNode, actions?: ReactNode) => (
    <StandaloneScreen
      title={strings.invitationAccept.title}
      back={false}
      onClose={outcome ? undefined : leave}
      actions={actions}
    >
      {body}
    </StandaloneScreen>
  );

  const scene = (
    illustration: IllustrationName,
    title: string,
    text: ReactNode,
    extra?: ReactNode,
  ) => (
    <>
      <SceneBanner name={illustration} height={170} width={210} />
      <PageTitle subtitle={text}>{title}</PageTitle>
      {extra}
    </>
  );

  const closeActions = (
    <BottomActions>
      <ActionButton kind="s" onClick={leave}>
        {strings.common.close}
      </ActionButton>
    </BottomActions>
  );

  if (!token) {
    const s = inactiveScene('unknown', null);
    return frame(scene(s.illustration, s.title, s.text), closeActions);
  }

  if (preview.isPending) {
    return frame(
      <div className="ui-pad" role="status" aria-label={strings.invitationAccept.loading}>
        <SkeletonBlock height={170} radius={24} />
        <SkeletonRows rows={4} />
      </div>,
    );
  }

  if (preview.isError && !isInvalidInvitationError(preview.error)) {
    return frame(<ErrorState error={preview.error} onRetry={() => void preview.refetch()} />, closeActions);
  }
  if (preview.isError || preview.data.state !== 'active') {
    const s = inactiveScene(
      preview.isError ? 'unknown' : preview.data.state,
      preview.isError ? null : preview.data.expires_at,
    );
    return frame(scene(s.illustration, s.title, s.text), closeActions);
  }

  const invitation = preview.data;
  const organizationName = invitation.organization_name ?? '';

  if (outcome === 'rejected' || outcome === 'expired') {
    const s =
      outcome === 'expired'
        ? inactiveScene('expired', null)
        : {
            illustration: 'status-cancel' as const,
            title: strings.invitationAccept.rejectedTitle,
            text: strings.invitationAccept.rejectedText,
          };
    return frame(scene(s.illustration, s.title, s.text), closeActions);
  }

  if (outcome === 'awaiting') {
    return frame(
      scene(
        'status-waiting',
        strings.invitationAccept.awaitingTitle,
        <span role="status">{strings.invitationAccept.awaitingText}</span>,
      ),
      <BottomActions>
        <ActionButton kind="s" onClick={() => navigate('/organizations', { replace: true })}>
          {strings.invitationAccept.toOrganizations}
        </ActionButton>
      </BottomActions>,
    );
  }

  if (outcome === 'joined') {
    const places = invitation.location_names;
    return frame(
      scene(
        'welcome-handshake',
        strings.invitationAccept.joinedTitle,
        <span role="status">
          {places.length > 1
            ? strings.invitationAccept.joinedPlacesText(places.join(', '))
            : strings.invitationAccept.joinedText(places[0] ?? null)}
        </span>,
      ),
      <BottomActions>
        <ActionButton onClick={() => navigate('/', { replace: true })}>
          {strings.invitationAccept.toHome}
        </ActionButton>
      </BottomActions>,
    );
  }

  const handleAccept = async () => {
    setAcceptError(null);
    try {
      const membership = await acceptInvitation.mutateAsync(token);
      if (location.search) navigate(location.pathname, { replace: true });
      await refreshMemberships();
      if (membership.status === 'pending') {
        setOutcome('awaiting');
        return;
      }
      activateMembership(membership);
      setOutcome('joined');
    } catch (error) {
      if (error instanceof ApiError && error.code === 'INVITATION_INVALID') {
        setOutcome(error.details?.reason === 'expired' ? 'expired' : 'rejected');
        return;
      }
      setAcceptError(error instanceof ApiError ? error.message : strings.common.unknownError);
    }
  };

  return frame(
    scene(
      'invitation',
      strings.invitationAccept.heroTitle(organizationName),
      (invitation.role && strings.invitationAccept.roleText[invitation.role]) ?? undefined,
      <>
        <KeyValueRows rows={detailRows(invitation)} aria-label={strings.invitationAccept.title} />
        {acceptError && <Banner tone="x" role="alert" title={acceptError} />}
      </>,
    ),
    <BottomActions>
      <ActionButton loading={acceptInvitation.isPending} onClick={() => void handleAccept()}>
        {strings.invitationAccept.acceptButton}
      </ActionButton>
    </BottomActions>,
  );
}
