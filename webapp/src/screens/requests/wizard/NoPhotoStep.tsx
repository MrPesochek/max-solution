import { strings } from '../../../strings/ru';
import { PageTitle } from '../../../ui/blocks/Blocks';
import { TextAreaField } from '../../../ui/FormField';
import { List, ListRow } from '../../../ui/List';
import { OTHER_REASON } from './helpers';

const t = strings.requests.wizard;

interface NoPhotoStepProps {
  choice: string | null;
  otherText: string;
  onChoiceChange: (choice: string) => void;
  onOtherTextChange: (value: string) => void;
}

export function NoPhotoStep({ choice, otherText, onChoiceChange, onOtherTextChange }: NoPhotoStepProps) {
  return (
    <>
      <PageTitle subtitle={t.noPhotoHint}>{t.noPhotoTitle}</PageTitle>
      <List role="radiogroup" aria-label={t.noPhotoTitle}>
        {t.noPhotoReasons.map((reason) => (
          <ListRow
            key={reason}
            title={reason}
            control={{ type: 'radio', checked: choice === reason }}
            onToggle={() => onChoiceChange(reason)}
          />
        ))}
        <ListRow
          title={t.noPhotoOther}
          control={{ type: 'radio', checked: choice === OTHER_REASON }}
          onToggle={() => onChoiceChange(OTHER_REASON)}
        />
      </List>
      {choice === OTHER_REASON && (
        <TextAreaField
          id="wizard-no-photo-reason"
          label={t.noPhotoOtherLabel}
          placeholder={t.noPhotoOtherPlaceholder}
          value={otherText}
          onChange={onOtherTextChange}
          rows={2}
          autoFocus
        />
      )}
    </>
  );
}
