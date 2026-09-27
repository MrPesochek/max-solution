import { useMemo, useState, type ReactNode } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import {
  useAcceptBindingInvitation,
  useBindingInvitationPreview,
  useDeclineBindingInvitation,
} from '../../api/hooks/useBindings';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import { ApiError } from '../../api/errors';
import { Skeleton } from '../../components/states/Skeleton';
import { EmptyState } from '../../components/states/EmptyState';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { useSession } from '../../session/SessionContext';
import { canManageBindings } from '../../lib/roles';
import type { BindingInvitationItem, BindingInvitationPreview, Equipment } from '../../api/types';
import { useEquipmentCategories } from '../../api/hooks/useDirectories';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note, PageTitle } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { TextAreaField } from '../../ui/FormField';
import { Sheet } from '../../ui/Sheet';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { shortDateTime } from '../../ui/format';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { EquipmentIcon } from '../../ui/EquipmentIcon';
import { CheckMark } from '../../ui/Check';
import { equipmentIllustration, type IllustrationName } from '../../ui/illustrations';
import { equipmentTitle } from '../requests/components/equipmentName';
import { isInvalidInvitationError } from '../invitations/invitationErrors';
import { shortDate } from './bindingView';
import './bindings.css';

function itemTitle(item: BindingInvitationItem): string {
  return item.description ?? item.model ?? item.serial_number ?? strings.bindings.acceptItemFallback(item.index + 1);
}

function guarantorRow(preview: BindingInvitationPreview): KeyValueRow | null {
  const kind = preview.guarantor_kind ?? null;
  const name = preview.guarantor_name?.trim() || null;
  if (!kind && !name) return null;
  const value =
    kind === 'service_org' || (!kind && name)
      ? name ?? preview.provider_name
      : strings.bindings.acceptGuarantorValue(strings.bindings.guarantorKind[kind!], name);
  return {
    label: strings.bindings.acceptGuarantor,
    hint: kind === 'manufacturer' ? strings.bindings.acceptGuarantorManufacturerHint : strings.bindings.acceptGuarantorHint,
    value,
  };
}

function addEquipmentHref(token: string, item?: BindingInvitationItem | null): string {
  const query = new URLSearchParams({ returnTo: `/bindings/accept?token=${encodeURIComponent(token)}` });
  if (item?.model) query.set('model', item.model);
  return `/equipment/new?${query.toString()}`;
}

function normalizeSerial(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase();
}

function initialMatches(items: BindingInvitationItem[], own: Equipment[]): Record<number, string> {
  const result: Record<number, string> = {};
  const used = new Set<string>();
  for (const item of items) {
    const serial = normalizeSerial(item.serial_number);
    if (!serial) continue;
    const found = own.filter((e) => normalizeSerial(e.serial_number) === serial);
    if (found.length === 1 && !used.has(found[0]!.id)) {
      result[item.index] = found[0]!.id;
      used.add(found[0]!.id);
    }
  }
  return result;
}

function verifiedText(preview: BindingInvitationPreview): string {
  if (preview.requisites_verified && preview.representative_verified) return strings.bindings.acceptVerified;
  if (preview.requisites_verified) return strings.bindings.acceptVerifiedRequisites;
  if (preview.representative_verified) return strings.bindings.acceptVerifiedRepresentative;
  return strings.bindings.acceptNotVerified;
}

function MatchSheet({
  item,
  options,
  value,
  locationNames,
  iconOf,
  addHref,
  onSelect,
  onClose,
}: {
  item: BindingInvitationItem | null;
  options: Equipment[];
  value: string | undefined;
  locationNames: Map<string, string>;
  iconOf: (equipment: Equipment) => IllustrationName;
  addHref: string;
  onSelect: (equipmentId: string | null) => void;
  onClose: () => void;
}) {
  const name = item ? itemTitle(item) : '';
  return (
    <Sheet
      open={item !== null}
      title={strings.bindings.acceptPickTitle}
      description={item ? [name, item.serial_number ? strings.bindings.acceptItemSerial(item.serial_number) : null].filter(Boolean).join(' · ') : undefined}
      onClose={onClose}
      actions={
        <>
          {value && (
            <ActionButton kind="s" onClick={() => onSelect(null)}>
              {strings.bindings.acceptPickClear}
            </ActionButton>
          )}
          <ActionButton kind="s" to={addHref}>
            {strings.bindings.acceptAddEquipment}
          </ActionButton>
        </>
      }
    >
      <List role="radiogroup" aria-label={strings.bindings.acceptPickList(name)}>
        {options.map((e) => {
          const title = equipmentTitle(e);
          return (
            <ListRow
              key={e.id}
              title={title}
              subtitle={[locationNames.get(e.location_id), e.serial_number ? strings.bindings.acceptItemSerial(e.serial_number) : null]
                .filter(Boolean)
                .join(' · ')}
              media={iconOf(e)}
              control={{ type: 'radio', checked: value === e.id }}
              onToggle={() => onSelect(e.id)}
            />
          );
        })}
      </List>
    </Sheet>
  );
}

function DeclineSheet({
  open,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  open: boolean;
  pending: boolean;
  error: string | null;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  return (
    <Sheet
      open={open}
      role="alertdialog"
      title={strings.bindings.acceptDeclineTitle}
      description={strings.bindings.acceptDeclineText}
      onClose={onClose}
      locked={pending}
      actions={
        <>
          <ActionButton kind="d" loading={pending} onClick={() => onConfirm(reason.trim())}>
            {strings.bindings.acceptDeclineConfirm}
          </ActionButton>
          <ActionButton kind="s" disabled={pending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id="binding-decline-reason"
        label={strings.bindings.acceptDeclineReasonLabel}
        placeholder={strings.equipment.optionalPlaceholder}
        value={reason}
        onChange={setReason}
      />
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Sheet>
  );
}

export function BindingAcceptScreen() {
  const [searchParams] = useSearchParams();
  const [token] = useState(() => searchParams.get('token'));
  const navigate = useNavigate();
  const location = useLocation();
  const dropTokenFromUrl = () => {
    if (location.search) navigate(location.pathname, { replace: true });
  };
  const { activeMembership } = useSession();
  const preview = useBindingInvitationPreview(token);
  const equipment = useOrgEquipment();
  const locations = useLocations();
  const categories = useEquipmentCategories();
  const acceptInvitation = useAcceptBindingInvitation();
  const declineInvitation = useDeclineBindingInvitation();
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineError, setDeclineError] = useState<string | null>(null);

  const [matches, setMatches] = useState<Record<number, string> | null>(null);
  const [pickIndex, setPickIndex] = useState<number | null>(null);
  const [mismatchIndex, setMismatchIndex] = useState<number | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [acceptedCount, setAcceptedCount] = useState<number | null>(null);

  const locationNames = useMemo(
    () => new Map((locations.data ?? []).map((l) => [l.id, l.name])),
    [locations.data],
  );
  const iconOf = (e: Equipment): IllustrationName => {
    const category = categories.data?.find((c) => c.id === e.equipment_category_id);
    return equipmentIllustration(category?.code, category?.name ?? equipmentTitle(e));
  };

  const title = strings.bindings.acceptTitle;
  const close = () => navigate('/bindings');
  const frame = (body: ReactNode, actions?: ReactNode) => (
    <Screen title={title} back={false} onClose={close} actions={actions}>
      {body}
    </Screen>
  );
  const done = (
    <BottomActions>
      <ActionButton kind="s" onClick={close}>
        {strings.bindings.done}
      </ActionButton>
    </BottomActions>
  );
  const invalid = frame(
    <EmptyState
      illustration="status-cancel"
      top={40}
      title={strings.bindings.acceptInvalid}
      description={strings.bindings.acceptInvalidDescription}
    />,
  );

  if (!token) return invalid;
  if (activeMembership && !canManageBindings(activeMembership.role)) return frame(<NoAccessState />);
  if (preview.isPending || equipment.isPending) return frame(<Skeleton lines={5} />);
  if (preview.isError && !isInvalidInvitationError(preview.error)) {
    return frame(<ErrorState error={preview.error} onRetry={() => void preview.refetch()} />);
  }
  if (preview.isError) return invalid;
  if (preview.data.state === 'declined') {
    return frame(
      <>
        <SceneBanner name="status-cancel" />
        <div role="status">
          <PageTitle subtitle={strings.bindings.acceptDeclinedText(preview.data.provider_name)}>
            {strings.bindings.acceptDeclined}
          </PageTitle>
        </div>
      </>,
      done,
    );
  }
  if (acceptedCount !== null) {
    return frame(
      <>
        <SceneBanner name="service-linked" />
        <div role="status">
          <PageTitle
            subtitle={strings.bindings.acceptSuccessText(
              strings.bindings.invitationUnits(acceptedCount),
              preview.data.provider_name,
            )}
          >
            {strings.bindings.acceptSuccess}
          </PageTitle>
        </div>
      </>,
      done,
    );
  }
  if (preview.data.state !== 'active') return invalid;
  if (!preview.data.details_disclosed) {
    return frame(
      <EmptyState
        illustration="status-cancel"
        top={40}
        title={strings.bindings.acceptInvalid}
        description={strings.bindings.acceptNotDisclosedDescription}
      />,
    );
  }

  if (equipment.isError) {
    return frame(<ErrorState error={equipment.error} onRetry={() => void equipment.refetch()} />);
  }

  const data = preview.data;
  const items = data.equipment_items;
  const ownEquipment: Equipment[] = equipment.data ?? [];
  const current = matches ?? initialMatches(items, ownEquipment);
  const allMatched = items.length > 0 && items.every((item) => Boolean(current[item.index]));
  const mismatchItem = items.find((i) => i.index === mismatchIndex);
  const pickItem = items.find((i) => i.index === pickIndex) ?? null;

  const setMatch = (index: number, equipmentId: string | null) => {
    const next = { ...current };
    if (equipmentId) next[index] = equipmentId;
    else delete next[index];
    setMatches(next);
    if (mismatchIndex === index) setMismatchIndex(null);
  };

  const handleConfirm = async () => {
    setAcceptError(null);
    setMismatchIndex(null);
    if (!allMatched) return;
    try {
      const result = await acceptInvitation.mutateAsync({
        token,
        matches: items.map((item) => ({ item_index: item.index, equipment_id: current[item.index]! })),
      });
      setAcceptedCount(result.length || items.length);
      dropTokenFromUrl();
    } catch (error) {
      if (error instanceof ApiError && error.code === 'SERIAL_NUMBER_MISMATCH') {
        setMismatchIndex(Number(error.details?.item_index));
        return;
      }
      setAcceptError(error instanceof ApiError ? error.message : strings.common.unknownError);
    }
  };

  const handleDecline = async (reason: string) => {
    setDeclineError(null);
    try {
      await declineInvitation.mutateAsync({ token, reason: reason || null });
      setDeclineOpen(false);
      dropTokenFromUrl();
    } catch (error) {
      setDeclineError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  const guarantor = guarantorRow(data);
  const rows: KeyValueRow[] = [
    {
      label: strings.bindings.acceptBasis,
      value: data.contract_number
        ? strings.bindings.contractShort(data.contract_number)
        : data.basis
          ? strings.bindings.basisLabel[data.basis]
          : strings.common.notSpecified,
    },
    ...(data.valid_until || data.valid_from
      ? [
          {
            label: strings.bindings.acceptTerm,
            value: data.valid_until
              ? strings.bindings.until(shortDate(data.valid_until))
              : shortDate(data.valid_from),
          },
        ]
      : []),
    ...(guarantor ? [guarantor] : []),
    { label: strings.bindings.acceptExpires, value: shortDateTime(data.expires_at) },
  ];

  const pickOptions = pickItem
    ? ownEquipment.filter(
        (e) =>
          !Object.entries(current).some(([index, id]) => Number(index) !== pickItem.index && id === e.id),
      )
    : [];

  return (
    <Screen
      title={title}
      back={false}
      onClose={close}
      actions={
        <BottomActions layout="row">
          <ActionButton kind="s" disabled={acceptInvitation.isPending} onClick={() => setDeclineOpen(true)}>
            {strings.bindings.acceptDecline}
          </ActionButton>
          <ActionButton
            disabled={!allMatched}
            loading={acceptInvitation.isPending}
            onClick={() => void handleConfirm()}
          >
            {strings.bindings.acceptConfirm}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="service-invitation" />
      <PageTitle subtitle={strings.bindings.acceptLead}>{strings.bindings.acceptOffer(data.provider_name)}</PageTitle>
      <p className="bd-verified">{verifiedText(data)}</p>
      <KeyValueRows rows={rows} />

      {mismatchItem && (
        <Banner tone="x" title={strings.bindings.acceptSerialMismatchTitle} role="alert">
          {strings.bindings.acceptSerialMismatch(itemTitle(mismatchItem))}
        </Banner>
      )}
      <section className="bd-items" aria-labelledby="binding-items-caption">
        <h3 id="binding-items-caption" className="bd-items__caption">
          {strings.bindings.acceptItemsCaption}
        </h3>
        {ownEquipment.length === 0 ? (
          <>
            <Note tone="error">{strings.bindings.acceptNoEquipment}</Note>
            <ActionButton kind="s" to={addEquipmentHref(token, items[0])}>
              {strings.bindings.acceptAddEquipment}
            </ActionButton>
          </>
        ) : (
          items.map((item) => {
            const name = itemTitle(item);
            const matched = ownEquipment.find((e) => e.id === current[item.index]);
            const error = mismatchIndex === item.index;
            const sub = error
              ? strings.bindings.acceptSerialMismatchTitle
              : matched
                ? strings.bindings.acceptItemMatched(equipmentTitle(matched), locationNames.get(matched.location_id) ?? null)
                : [item.serial_number ? strings.bindings.acceptItemSerial(item.serial_number) : null, strings.bindings.acceptItemPick]
                    .filter(Boolean)
                    .join(' · ');
            return (
              <button
                key={item.index}
                type="button"
                className="bd-item"
                aria-haspopup="dialog"
                aria-label={strings.bindings.acceptItemButton(name, sub)}
                aria-invalid={error || undefined}
                onClick={() => setPickIndex(item.index)}
              >
                <EquipmentIcon name={[item.description, item.model].filter(Boolean).join(' ')} width={48} />
                <span className="bd-item__main">
                  <span className="bd-item__title">{name}</span>
                  <span
                    className={`bd-item__sub${error ? ' bd-item__sub--error' : matched ? '' : ' bd-item__sub--pick'}`}
                  >
                    {sub}
                  </span>
                </span>
                <CheckMark checked={Boolean(matched) && !error} />
              </button>
            );
          })
        )}
      </section>

      {acceptError && (
        <Note tone="error" role="alert">
          {acceptError}
        </Note>
      )}
      <Note>{allMatched || items.length === 0 ? strings.bindings.acceptOfferText : strings.bindings.acceptMatchHint}</Note>
      <MatchSheet
        item={pickItem}
        options={pickOptions}
        value={pickItem ? current[pickItem.index] : undefined}
        locationNames={locationNames}
        iconOf={iconOf}
        addHref={addEquipmentHref(token, pickItem)}
        onSelect={(id) => {
          if (pickItem) setMatch(pickItem.index, id);
          setPickIndex(null);
        }}
        onClose={() => setPickIndex(null)}
      />
      <DeclineSheet
        open={declineOpen}
        pending={declineInvitation.isPending}
        error={declineError}
        onConfirm={(reason) => void handleDecline(reason)}
        onClose={() => {
          setDeclineOpen(false);
          setDeclineError(null);
        }}
      />
    </Screen>
  );
}
