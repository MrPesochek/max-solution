import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { canEditRequisites, canSubmitProfile } from '../../../lib/trust';
import { isValidInn } from '../../../lib/inn';
import {
  useSubmitProviderProfile,
  useUpdateProviderProfile,
} from '../../../api/hooks/useProviderProfile';
import type { City, EquipmentCategory, ProviderProfile } from '../../../api/types';
import { actionErrorMessage } from '../../../components/actions/actionErrors';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { PhoneField, TextField } from '../../../ui/FormField';
import { ChoiceCard, ChoiceGroup } from '../../../ui/ChoiceCard';
import { ChipGroup } from '../../../ui/Chips';
import { EvidenceTile } from '../components/EvidenceTile';
import { draftFromProfile, payloadFromDraft, type ProfileDraft } from './profileDraft';

type Step = 'type' | 'details' | 'representative';

const MAX_EVIDENCE_BYTES = 10 * 1024 * 1024;

export function ProviderRegistrationForm({
  profile,
  cities,
  categories,
}: {
  profile: ProviderProfile;
  cities: City[];
  categories: EquipmentCategory[];
}) {
  const navigate = useNavigate();
  const updateProfile = useUpdateProviderProfile();
  const submitProfile = useSubmitProviderProfile();
  const editableRequisites = canEditRequisites(profile.status);
  const submittable = canSubmitProfile(profile.status);
  const steps: Step[] = editableRequisites ? ['type', 'details', 'representative'] : ['details'];

  const [step, setStep] = useState<Step>(steps[0]!);
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFromProfile(profile));
  const [innError, setInnError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [powerDocument, setPowerDocument] = useState<File | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const busy = updateProfile.isPending || submitProfile.isPending;
  const isCompany = draft.typeChoice === 'company';

  const index = steps.indexOf(step);
  const last = index === steps.length - 1;
  const set = <K extends keyof ProfileDraft>(key: K, value: ProfileDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const toProfile = () => navigate('/provider/profile');
  const back = () => (index > 0 ? setStep(steps[index - 1]!) : toProfile());

  const save = async (): Promise<boolean> => {
    setFormError(null);
    if (editableRequisites && draft.inn.trim() && !isValidInn(draft.inn)) {
      setInnError(strings.provider.innInvalid);
      setStep('details');
      return false;
    }
    setInnError(null);
    try {
      await updateProfile.mutateAsync(payloadFromDraft(draft, editableRequisites));
      return true;
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
      return false;
    }
  };

  const next = async () => {
    if (!(await save())) return;
    if (!last) {
      setStep(steps[index + 1]!);
      return;
    }
    if (!submittable) {
      toProfile();
      return;
    }
    try {
      await submitProfile.mutateAsync();
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
      return;
    }
    const state = powerDocument && isCompany ? { pendingDocument: powerDocument } : undefined;
    setTimeout(() => navigate('/provider/verification', { state }), 0);
  };

  const pickDocument = (file: File) => {
    if (file.size > MAX_EVIDENCE_BYTES) {
      setDocumentError(strings.orgForm.docTooLarge);
      return;
    }
    setDocumentError(null);
    setPowerDocument(file);
  };

  const toggleCategory = (categoryId: string, checked: boolean) =>
    set(
      'categoryIds',
      checked
        ? [...draft.categoryIds, categoryId]
        : draft.categoryIds.filter((id) => id !== categoryId),
    );

  const toggleCity = (cityId: string, serve: boolean) =>
    set(
      'areas',
      serve
        ? [...draft.areas, { city_id: cityId, district_ids: [] }]
        : draft.areas.filter((a) => a.city_id !== cityId),
    );

  const toggleDistrict = (cityId: string, districtId: string, checked: boolean) =>
    set(
      'areas',
      draft.areas.map((a) =>
        a.city_id !== cityId
          ? a
          : {
              ...a,
              district_ids: checked
                ? [...a.district_ids, districtId]
                : a.district_ids.filter((id) => id !== districtId),
            },
      ),
    );

  const nextLabel = !last
    ? strings.provider.next
    : submittable
      ? strings.provider.submit
      : strings.common.save;

  return (
    <Screen
      title={strings.provider.registrationTitle}
      subtitle={steps.length > 1 ? strings.provider.stepOf(index + 1, steps.length) : undefined}
      back={back}
      actions={
        <BottomActions>
          <ActionButton loading={busy} onClick={() => void next()}>
            {nextLabel}
          </ActionButton>
        </BottomActions>
      }
    >
      {step === 'type' && (
        <>
          <PageTitle subtitle={strings.provider.typeStepText}>
            {strings.orgForm.providerTitle}
          </PageTitle>
          <ChoiceGroup label={strings.provider.typeLabel}>
            <ChoiceCard
              title={strings.orgForm.providerCompany}
              subtitle={strings.orgForm.providerCompanyHint}
              selected={isCompany}
              onSelect={() => set('typeChoice', 'company')}
            />
            <ChoiceCard
              title={strings.orgForm.providerSelf}
              subtitle={strings.orgForm.providerSelfHint}
              selected={!isCompany}
              onSelect={() => {
                if (isCompany) set('typeChoice', 'self_employed');
              }}
            />
          </ChoiceGroup>
          {!isCompany && (
            <div className="onb-subchoice">
              <ChipGroup
                label={strings.orgForm.legalFormLabel}
                value={draft.typeChoice}
                onChange={(value) => set('typeChoice', value)}
                options={[
                  { value: 'self_employed', label: strings.orgForm.legalFormSelfEmployed },
                  { value: 'ip', label: strings.orgForm.legalFormIp },
                ]}
              />
            </div>
          )}
        </>
      )}

      {step === 'details' && (
        <>
          {editableRequisites ? (
            <TextField
              id="provider-inn"
              label={strings.provider.innLabel}
              className="ui-field__control--mono"
              inputMode="numeric"
              placeholder={strings.provider.innPlaceholder}
              value={draft.inn}
              error={innError}
              hint={
                draft.inn.trim()
                  ? draft.inn.trim().length === 10
                    ? strings.provider.innHintOrganization
                    : strings.provider.innHintIndividual
                  : undefined
              }
              onChange={(value) => {
                setInnError(null);
                set('inn', value.replace(/\D/g, ''));
              }}
            />
          ) : (
            <Note>{strings.provider.requisitesLockedNotice}</Note>
          )}
          <TextField
            id="provider-name"
            label={strings.provider.nameLabel}
            value={profile.name}
            readOnly
            disabled
          />

          <SectionCaption>{strings.provider.categoriesCaption}</SectionCaption>
          <List role="group" aria-label={strings.provider.categoriesCaption}>
            {categories.map((category) => (
              <ListRow
                key={category.id}
                title={category.name}
                control={{ type: 'checkbox', checked: draft.categoryIds.includes(category.id) }}
                onToggle={(checked) => toggleCategory(category.id, checked)}
              />
            ))}
          </List>

          <SectionCaption>{strings.provider.areasCaption}</SectionCaption>
          {cities.map((city) => {
            const area = draft.areas.find((a) => a.city_id === city.id);
            return (
              <List key={city.id} role="group" aria-label={city.name}>
                <ListRow
                  title={city.name}
                  subtitle={
                    area && area.district_ids.length === 0
                      ? strings.provider.areaWholeCity
                      : undefined
                  }
                  aria-label={`${strings.provider.areaServeCity}: ${city.name}`}
                  control={{ type: 'checkbox', checked: Boolean(area) }}
                  onToggle={(checked) => toggleCity(city.id, checked)}
                />
                {area &&
                  city.districts.map((district) => (
                    <ListRow
                      key={district.id}
                      title={district.name}
                      control={{
                        type: 'checkbox',
                        checked: area.district_ids.includes(district.id),
                      }}
                      onToggle={(checked) => toggleDistrict(city.id, district.id, checked)}
                    />
                  ))}
              </List>
            );
          })}
          <Note>{strings.provider.areaHint}</Note>

          {draft.categoryIds.length > 0 && (
            <>
              <SectionCaption>{strings.provider.sectionBrands}</SectionCaption>
              {draft.categoryIds.map((categoryId) => {
                const category = categories.find((c) => c.id === categoryId);
                if (!category) return null;
                return (
                  <TextField
                    key={categoryId}
                    id={`brands-${categoryId}`}
                    label={category.name}
                    placeholder={strings.provider.brandsPlaceholder}
                    value={draft.brandsByCategory[categoryId] ?? ''}
                    onChange={(value) =>
                      set('brandsByCategory', { ...draft.brandsByCategory, [categoryId]: value })
                    }
                  />
                );
              })}
              <Note>{strings.provider.brandsHint}</Note>
            </>
          )}
        </>
      )}

      {step === 'representative' && (
        <>
          <PageTitle subtitle={strings.provider.representativeText}>
            {strings.provider.representativeTitle}
          </PageTitle>
          <TextField
            id="provider-contact-name"
            label={strings.provider.contactName}
            autoComplete="name"
            value={draft.contactName}
            onChange={(value) => set('contactName', value)}
          />
          <TextField
            id="provider-representative-position"
            label={strings.provider.representativePosition}
            placeholder={strings.provider.representativePositionPlaceholder}
            autoComplete="organization-title"
            value={draft.representativePosition}
            onChange={(value) => set('representativePosition', value)}
          />
          <PhoneField
            id="provider-contact-phone"
            label={strings.provider.contactPhone}
            value={draft.contactPhone}
            onChange={(value) => set('contactPhone', value)}
          />
          <TextField
            id="provider-contact-email"
            type="email"
            label={strings.provider.contactEmail}
            value={draft.contactEmail}
            onChange={(value) => set('contactEmail', value)}
          />
          <Note>{strings.provider.representativeNote}</Note>
          {isCompany && (
            <section aria-labelledby="provider-power">
              <SectionCaption id="provider-power">{strings.orgForm.powerTitle}</SectionCaption>
              <EvidenceTile
                files={powerDocument ? [powerDocument] : []}
                inputLabel={strings.orgForm.docPick}
                onPick={pickDocument}
                onRemove={() => setPowerDocument(null)}
                disabled={busy}
              />
              {documentError && (
                <Note tone="error" role="alert">
                  {documentError}
                </Note>
              )}
              <Note>{strings.orgForm.powerNote}</Note>
            </section>
          )}
        </>
      )}

      {formError && (
        <Note tone="error" role="alert">
          {formError}
        </Note>
      )}
    </Screen>
  );
}
