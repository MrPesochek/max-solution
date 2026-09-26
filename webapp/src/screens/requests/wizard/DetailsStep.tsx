import type { ReactNode } from 'react';
import { strings } from '../../../strings/ru';
import type { Urgency } from '../../../api/types';
import { PageTitle } from '../../../ui/blocks/Blocks';
import { ChipGroup } from '../../../ui/Chips';
import { TextAreaField, TextField } from '../../../ui/FormField';
import { Segmented } from '../../../ui/Segmented';

const t = strings.requests.wizard;
const URGENCY_OPTIONS: Urgency[] = ['critical', 'urgent', 'normal'];

interface DetailsStepProps {
  equipmentLine: ReactNode;
  notice?: ReactNode;
  presets: readonly string[];
  symptoms: string[];
  onSymptomsChange: (value: string[]) => void;
  details: string;
  onDetailsChange: (value: string) => void;
  descriptionError?: string;
  errorCode: string;
  onErrorCodeChange: (value: string) => void;
  photos: ReactNode;
  urgency: Urgency;
  onUrgencyChange: (value: Urgency) => void;
}

export function DetailsStep({
  equipmentLine,
  notice,
  presets,
  symptoms,
  onSymptomsChange,
  details,
  onDetailsChange,
  descriptionError,
  errorCode,
  onErrorCodeChange,
  photos,
  urgency,
  onUrgencyChange,
}: DetailsStepProps) {
  return (
    <div className="wizard-details">
      <PageTitle subtitle={equipmentLine}>{t.detailsTitle}</PageTitle>
      {notice}
      <ChipGroup
        multiple
        label={t.symptomsGroupLabel}
        options={presets.map((preset) => ({ value: preset, label: preset }))}
        value={symptoms}
        onChange={onSymptomsChange}
      />
      <TextAreaField
        id="wizard-symptoms"
        label={t.symptomsLabel}
        value={details}
        onChange={onDetailsChange}
        placeholder={t.symptomsPlaceholder}
        rows={3}
        required
        error={descriptionError}
      />
      <TextField
        id="wizard-error-code"
        label={t.errorCodeLabel}
        value={errorCode}
        onChange={onErrorCodeChange}
        placeholder={t.errorCodePlaceholder}
        autoComplete="off"
      />
      {photos}
      <h3 className="wizard-label" id="wizard-urgency-label">
        {t.urgencyLabel}
      </h3>
      <Segmented
        label={t.urgencyLabel}
        items={URGENCY_OPTIONS.map((option) => ({ id: option, label: t.urgencyOption[option] }))}
        value={urgency}
        onChange={onUrgencyChange}
      />
    </div>
  );
}
