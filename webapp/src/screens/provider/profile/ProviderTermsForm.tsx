import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { canEditRequisites } from '../../../lib/trust';
import { useUpdateProviderProfile } from '../../../api/hooks/useProviderProfile';
import type { ProviderProfile } from '../../../api/types';
import { actionErrorMessage } from '../../../components/actions/actionErrors';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { TextAreaField, TextField } from '../../../ui/FormField';
import { draftFromProfile, payloadFromDraft, type ProfileDraft } from './profileDraft';

export function ProviderTermsForm({ profile }: { profile: ProviderProfile }) {
  const navigate = useNavigate();
  const updateProfile = useUpdateProviderProfile();
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFromProfile(profile));
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof ProfileDraft>(key: K, value: ProfileDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const save = async () => {
    setError(null);
    try {
      await updateProfile.mutateAsync(payloadFromDraft(draft, canEditRequisites(profile.status)));
      navigate('/provider/profile');
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <Screen
      title={strings.provider.visitTerms}
      back="/provider/profile"
      actions={
        <BottomActions>
          <ActionButton loading={updateProfile.isPending} onClick={() => void save()}>
            {strings.common.save}
          </ActionButton>
        </BottomActions>
      }
    >
      <TextField
        id="visit-price-from"
        label={strings.provider.visitPriceFromLabel}
        hint={strings.provider.visitPriceFromHint}
        inputMode="decimal"
        placeholder={strings.workspace.priceAmountPlaceholder}
        value={draft.visitPriceFrom}
        onChange={(value) => set('visitPriceFrom', value)}
      />
      <TextAreaField
        id="visit-terms"
        label={strings.provider.visitTerms}
        placeholder={strings.provider.visitTermsPlaceholder}
        value={draft.visitTerms}
        onChange={(value) => set('visitTerms', value)}
        rows={4}
      />
      <List>
        <ListRow
          title={strings.provider.canProvideDocuments}
          control={{ type: 'switch', checked: draft.canProvideDocuments }}
          onToggle={(checked) => set('canProvideDocuments', checked)}
        />
      </List>
      <TextAreaField
        id="provider-description"
        label={strings.provider.description}
        placeholder={strings.provider.descriptionPlaceholder}
        value={draft.description}
        onChange={(value) => set('description', value)}
        rows={4}
      />
      <Note>{profile.specialization_disclaimer}</Note>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Screen>
  );
}
