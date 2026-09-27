import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { providerSearchReady, useProviderSearch } from '../../api/hooks/useProviders';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import {
  useBindingRequestAttempts,
  useBindingsList,
  useCreateContactBinding,
  useRequestBinding,
  useRevokeBinding,
} from '../../api/hooks/useBindings';
import { ApiError } from '../../api/errors';
import type { BindingBasis, ProviderCatalogItem, ServiceBinding } from '../../api/types';
import { extractInviteToken } from '../onboarding/invitationToken';
import { useConfirm } from '../../components/useConfirm';
import { useSession } from '../../session/SessionContext';
import { canManageBindings } from '../../lib/roles';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { PhoneField, SelectField, TextField } from '../../ui/FormField';
import { StatusHero } from '../../ui/StatusHero';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { ChipGroup } from '../../ui/Chips';
import { equipmentTitle } from './bindingView';
import './bindings.css';

type Way = 'invite' | 'request' | 'contact';
const WAYS: Way[] = ['invite', 'request', 'contact'];
const BASES: BindingBasis[] = ['service_contract', 'warranty', 'preferred_provider'];

const RATE_LIMIT_WINDOW_MINUTES = 15;

const SEARCH_DELAY_MS = 300;

function useDebounced(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function ProviderPicker({
  selected,
  onSelect,
  error,
}: {
  selected: ProviderCatalogItem | null;
  onSelect: (provider: ProviderCatalogItem) => void;
  error?: string;
}) {
  const [query, setQuery] = useState('');
  const debounced = useDebounced(query, SEARCH_DELAY_MS);
  const search = useProviderSearch(debounced);
  const ready = providerSearchReady(debounced);
  const found = ready ? (search.data ?? []) : [];
  const rows = selected && !found.some((p) => p.id === selected.id) ? [selected, ...found] : found;
  const b = strings.bindings;
  return (
    <>
      <TextField
        id="binding-provider"
        label={b.requestProviderLabel}
        placeholder={b.requestProviderPlaceholder}
        value={query}
        onChange={setQuery}
        hint={query.trim() && !providerSearchReady(query) ? b.requestProviderHint : undefined}
        error={error}
        autoComplete="off"
        inputMode="search"
      />
      {ready && search.isPending && <Skeleton lines={2} />}
      {ready && search.isError && <ErrorState error={search.error} onRetry={() => void search.refetch()} />}
      {ready && search.isSuccess && found.length === 0 && <Note>{b.requestProviderNotFound}</Note>}
      {rows.length > 0 && (
        <List role="radiogroup" aria-label={b.requestProviderLabel}>
          {rows.map((provider) => (
            <ListRow
              key={provider.id}
              title={provider.name}
              control={{ type: 'radio', checked: selected?.id === provider.id }}
              onToggle={() => onSelect(provider)}
            />
          ))}
        </List>
      )}
    </>
  );
}

function retryMinutes(error: ApiError): number {
  const seconds = Number(error.details?.retry_after_seconds);
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds / 60) : RATE_LIMIT_WINDOW_MINUTES;
}

export function AddBindingScreen() {
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const wayParam = searchParams.get('way') as Way | null;
  const way = wayParam && WAYS.includes(wayParam) ? wayParam : null;
  const presetEquipment = searchParams.get('equipment');

  const equipment = useOrgEquipment();
  const locations = useLocations();
  const requestBinding = useRequestBinding();
  const createContact = useCreateContactBinding();
  const attemptsLeft = useBindingRequestAttempts();
  const bindings = useBindingsList();
  const revokeBinding = useRevokeBinding();

  const [invitationLink, setInvitationLink] = useState('');
  const [provider, setProvider] = useState<ProviderCatalogItem | null>(null);
  const providerId = provider?.id ?? '';
  const [contractNumber, setContractNumber] = useState('');
  const [basis, setBasis] = useState<BindingBasis>('service_contract');
  const [equipmentIds, setEquipmentIds] = useState<string[]>(() => (presetEquipment ? [presetEquipment] : []));
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [contactEquipmentId, setContactEquipmentId] = useState(presetEquipment ?? '');
  const [formError, setFormError] = useState<string | null>(null);
  const [requestSent, setRequestSent] = useState(false);
  const [rateLimitMinutes, setRateLimitMinutes] = useState<number | null>(null);
  const [contactSaved, setContactSaved] = useState(false);
  const [touched, setTouched] = useState(false);
  const { confirm, dialog } = useConfirm();

  const locationNames = useMemo(
    () => new Map((locations.data ?? []).map((l) => [l.id, l.name])),
    [locations.data],
  );

  const chooseWay = (next: Way | null) => {
    setFormError(null);
    setTouched(false);
    const params = new URLSearchParams(searchParams);
    if (next) params.set('way', next);
    else params.delete('way');
    setSearchParams(params, { replace: !next });
  };
  const exit = () => {
    if (presetEquipment) {
      const item = equipment.data?.find((e) => e.id === presetEquipment);
      if (item) {
        navigate(`/equipment/${item.location_id}/${item.id}`);
        return;
      }
    }
    navigate('/bindings');
  };

  if (!activeMembership) return null;
  if (!canManageBindings(activeMembership.role)) {
    return (
      <Screen title={strings.bindings.connectTitle}>
        <NoAccessState />
      </Screen>
    );
  }

  if (!way) {
    return (
      <Screen title={strings.bindings.connectTitle}>
        <PageTitle>{strings.bindings.connectQuestion}</PageTitle>
        <List>
          <ListRow
            title={strings.bindings.wayInvite}
            subtitle={strings.bindings.wayInviteText}
            onClick={() => chooseWay('invite')}
            chevron
          />
          <ListRow
            title={strings.bindings.wayRequest}
            subtitle={strings.bindings.wayRequestText}
            onClick={() => chooseWay('request')}
            chevron
          />
          <ListRow
            title={strings.bindings.wayContact}
            subtitle={strings.bindings.wayContactText}
            onClick={() => chooseWay('contact')}
            chevron
          />
        </List>
        <Note>{strings.bindings.connectNote}</Note>
      </Screen>
    );
  }

  const back = () => chooseWay(null);

  if (way === 'invite') {
    const openInvitation = (event?: FormEvent) => {
      event?.preventDefault();
      setTouched(true);
      const token = extractInviteToken(invitationLink, 'sb');
      if (token) navigate(`/bindings/accept?token=${encodeURIComponent(token)}`);
      else document.getElementById('accept-link')?.focus();
    };
    return (
      <Screen
        title={strings.bindings.acceptLinkTitle}
        back={back}
        actions={
          <BottomActions>
            <ActionButton type="submit" form="binding-invite-form">
              {strings.bindings.acceptLinkOpen}
            </ActionButton>
          </BottomActions>
        }
      >
        <form id="binding-invite-form" onSubmit={openInvitation} noValidate>
          <TextField
            id="accept-link"
            label={strings.bindings.acceptLinkLabel}
            value={invitationLink}
            onChange={setInvitationLink}
            autoComplete="off"
            required
            error={touched && !invitationLink.trim() ? strings.bindings.requiredLink : undefined}
          />
          <Note>{strings.bindings.acceptLinkHint}</Note>
        </form>
      </Screen>
    );
  }

  const loadingData = equipment.isPending;
  const dataError = equipment.error;
  const retryData = () => void equipment.refetch();

  if (way === 'request') {
    const presetItem = presetEquipment ? equipment.data?.find((e) => e.id === presetEquipment) : undefined;
    const title = presetItem ? equipmentTitle(presetItem) : strings.bindings.requestTitle;
    const providerName = provider?.name ?? strings.bindings.requestProviderLabel;
    if (rateLimitMinutes !== null) {
      return (
        <Screen
          title={title}
          back={() => setRateLimitMinutes(null)}
          actions={
            <BottomActions>
              <ActionButton onClick={() => setRateLimitMinutes(null)}>{strings.bindings.rateLimitOk}</ActionButton>
            </BottomActions>
          }
        >
          <StatusHero
            illustration="status-waiting"
            top={40}
            title={strings.bindings.rateLimitTitle(rateLimitMinutes)}
            role="alert"
          >
            {strings.bindings.rateLimitText}
          </StatusHero>
        </Screen>
      );
    }
    if (requestSent) {
      const cancelRequest = async () => {
        setFormError(null);
        const ok = await confirm({
          title: strings.bindings.requestCancelConfirm,
          description: strings.bindings.requestCancelConfirmText,
          confirmLabel: strings.bindings.requestCancel,
          destructive: true,
        });
        if (!ok) return;
        const pending = ((bindings.data ?? []) as ServiceBinding[]).filter(
          (b) =>
            !b.is_contact_only &&
            b.status === 'pending' &&
            b.provider.organization_id === providerId &&
            equipmentIds.includes(b.equipment_id),
        );
        try {
          for (const binding of pending) {
            await revokeBinding.mutateAsync({ id: binding.id, reason: strings.bindings.requestCancelReason });
          }
          setRequestSent(false);
        } catch (error) {
          setFormError(actionErrorMessage(error, strings.common.unknownError));
        }
      };
      return (
        <Screen
          title={title}
          back={exit}
          actions={
            <BottomActions>
              <ActionButton disabled={revokeBinding.isPending} onClick={exit}>
                {strings.bindings.done}
              </ActionButton>
            </BottomActions>
          }
        >
          <SceneBanner name="status-waiting" />
          <div role="status">
            <PageTitle subtitle={strings.bindings.requestSentText(providerName, contractNumber.trim())}>
              {strings.bindings.requestSentTitle}
            </PageTitle>
          </div>
          <KeyValueRows
            rows={[
              { label: strings.bindings.requestSentStatus, value: strings.bindings.requestSentStatusValue },
              { label: strings.bindings.requestSentBasis, value: strings.bindings.requestBasis[basis] },
            ]}
          />
          <Note>{strings.bindings.requestSentPrivacy}</Note>
          <List>
            <ListRow
              title={strings.bindings.requestCancel}
              action="danger"
              loading={revokeBinding.isPending}
              disabled={bindings.isFetching || revokeBinding.isPending}
              onClick={() => void cancelRequest()}
            />
          </List>
          {formError && (
            <Note tone="error" role="alert">
              {formError}
            </Note>
          )}
          {dialog}
        </Screen>
      );
    }

    const canSubmit = Boolean(providerId && contractNumber.trim() && equipmentIds.length > 0);
    const handleRequest = async (event: FormEvent) => {
      event.preventDefault();
      setFormError(null);
      setTouched(true);
      if (!canSubmit) {
        const first = !providerId ? 'binding-provider' : !contractNumber.trim() ? 'request-contract-number' : null;
        if (first) document.getElementById(first)?.focus();
        return;
      }
      if (requestBinding.isPending) return;
      try {
        await requestBinding.mutateAsync({
          provider_organization_id: providerId,
          contract_number: contractNumber.trim(),
          equipment_ids: equipmentIds,
          basis,
        });
        setRequestSent(true);
      } catch (error) {
        if (error instanceof ApiError && error.isRateLimited) {
          setRateLimitMinutes(retryMinutes(error));
          return;
        }
        setFormError(actionErrorMessage(error, strings.common.unknownError));
      }
    };

    return (
      <Screen
        title={title}
        back={back}
        actions={
          loadingData || dataError ? undefined : (
            <BottomActions>
              <ActionButton
                type="submit"
                form="binding-request-form"
                loading={requestBinding.isPending}
              >
                {strings.bindings.requestSubmit}
              </ActionButton>
            </BottomActions>
          )
        }
      >
        <PageTitle subtitle={strings.bindings.requestLead}>{strings.bindings.requestHeading}</PageTitle>
        {loadingData ? (
          <Skeleton lines={4} />
        ) : dataError ? (
          <ErrorState error={dataError} onRetry={retryData} />
        ) : (
          <form id="binding-request-form" onSubmit={(event) => void handleRequest(event)} noValidate>
            <ProviderPicker
              selected={provider}
              onSelect={setProvider}
              error={touched && !providerId ? strings.bindings.requiredProvider : undefined}
            />
            <TextField
              id="request-contract-number"
              label={strings.bindings.requestContractLabel}
              placeholder={strings.bindings.requestContractPlaceholder}
              value={contractNumber}
              onChange={setContractNumber}
              hint={strings.bindings.requestContractHint}
              autoComplete="off"
              required
              error={touched && !contractNumber.trim() ? strings.bindings.requiredContract : undefined}
            />
            <div className="bd-field">
              <span className="bd-field__label" aria-hidden="true">
                {strings.bindings.requestBasisLabel}
              </span>
              <ChipGroup
                label={strings.bindings.requestBasisLabel}
                value={basis}
                onChange={setBasis}
                options={BASES.map((value) => ({ value, label: strings.bindings.requestBasis[value] }))}
              />
            </div>
            {!presetItem && (
              <>
                <SectionCaption id="request-equipment">{strings.bindings.requestEquipmentLabel}</SectionCaption>
                <List role="group" aria-label={strings.bindings.requestEquipmentLabel}>
                  {(equipment.data ?? []).map((item) => {
                    const checked = equipmentIds.includes(item.id);
                    return (
                      <ListRow
                        key={item.id}
                        title={equipmentTitle(item)}
                        subtitle={[locationNames.get(item.location_id), item.serial_number].filter(Boolean).join(' · ')}
                        control={{ type: 'checkbox', checked }}
                        onToggle={(next) =>
                          setEquipmentIds((prev) => (next ? [...prev, item.id] : prev.filter((id) => id !== item.id)))
                        }
                      />
                    );
                  })}
                </List>
                {touched && equipmentIds.length === 0 && (
                  <Note tone="error" role="alert">
                    {strings.bindings.requiredEquipment}
                  </Note>
                )}
              </>
            )}
            {formError && (
              <Note tone="error" role="alert">
                {formError}
              </Note>
            )}
            <Note>
              {attemptsLeft !== null
                ? strings.bindings.requestAttemptsLeft(attemptsLeft)
                : strings.bindings.requestLimitNote}
            </Note>
          </form>
        )}
      </Screen>
    );
  }

  const title = strings.bindings.contactTitle;
  if (contactSaved) {
    return (
      <Screen
        title={title}
        back={exit}
        actions={
          <BottomActions>
            <ActionButton onClick={exit}>{strings.bindings.done}</ActionButton>
          </BottomActions>
        }
      >
        <StatusHero icon="✓" tone="ok" top={150} title={strings.bindings.contactSaved} role="status">
          {strings.bindings.contactSavedText}
        </StatusHero>
      </Screen>
    );
  }

  const canSave = Boolean(contactName.trim() && contactEquipmentId);
  const handleContact = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setTouched(true);
    if (!canSave) {
      document.getElementById(contactName.trim() ? 'contact-equipment' : 'contact-name')?.focus();
      return;
    }
    if (createContact.isPending) return;
    try {
      await createContact.mutateAsync({
        equipment_id: contactEquipmentId,
        contact_name: contactName.trim(),
        contact_phone: contactPhone.trim() || null,
      });
      setContactSaved(true);
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  return (
    <Screen
      title={title}
      back={back}
      actions={
        <BottomActions>
          <ActionButton type="submit" form="binding-contact-form" loading={createContact.isPending}>
            {strings.bindings.contactSubmit}
          </ActionButton>
        </BottomActions>
      }
    >
      <form id="binding-contact-form" onSubmit={(event) => void handleContact(event)} noValidate>
        <TextField
          id="contact-name"
          label={strings.bindings.contactNameLabel}
          value={contactName}
          onChange={setContactName}
          required
          error={touched && !contactName.trim() ? strings.bindings.requiredContactName : undefined}
        />
        <PhoneField
          id="contact-phone"
          label={strings.bindings.contactPhoneLabel}
          value={contactPhone}
          onChange={setContactPhone}
        />
        {equipment.isPending ? (
          <Skeleton lines={2} />
        ) : equipment.isError ? (
          <ErrorState error={equipment.error} onRetry={() => void equipment.refetch()} />
        ) : (
          <SelectField
            id="contact-equipment"
            label={strings.bindings.contactEquipmentLabel}
            value={contactEquipmentId}
            onChange={setContactEquipmentId}
            required
            error={touched && !contactEquipmentId ? strings.bindings.requiredContactEquipment : undefined}
            placeholder={strings.common.notSpecified}
            options={(equipment.data ?? []).map((item) => ({
              value: item.id,
              label: equipmentTitle(item),
            }))}
          />
        )}
        {formError && (
          <Note tone="error" role="alert">
            {formError}
          </Note>
        )}
        <Note>{strings.bindings.contactHint}</Note>
      </form>
    </Screen>
  );
}
