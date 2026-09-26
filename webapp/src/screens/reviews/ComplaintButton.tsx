import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { useCreateComplaint } from '../../api/hooks/useComplaints';
import type { ComplaintSubjectType } from '../../api/types';
import { Sheet } from '../../ui/Sheet';
import { List, ListRow } from '../../ui/List';
import { TextAreaField } from '../../ui/FormField';
import { Note } from '../../ui/blocks/Blocks';
import { ActionButton } from '../../ui/layout/ActionButton';

export interface ComplaintSubject {
  subjectType: ComplaintSubjectType;
  targetId: string;
  label?: string;
}

interface ComplaintButtonProps {
  subjectType: ComplaintSubjectType;
  targetId: string;
  subjects?: ComplaintSubject[];
  label?: string;
  size?: 'xsmall' | 'small' | 'medium' | 'large';
  variant?: 'button' | 'row';
}

const keyOf = (s: ComplaintSubject) => `${s.subjectType}:${s.targetId}`;

export function ComplaintButton({
  subjectType,
  targetId,
  subjects,
  label,
  variant = 'button',
}: ComplaintButtonProps) {
  const options: ComplaintSubject[] = subjects?.length ? subjects : [{ subjectType, targetId }];
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(() => keyOf(options[0]!));
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const createComplaint = useCreateComplaint();

  const current = options.find((o) => keyOf(o) === selected) ?? options[0]!;
  const trigger = label ?? strings.complaints.button[subjectType];

  const handleSubmit = async () => {
    if (!description.trim()) return;
    setError(null);
    try {
      await createComplaint.mutateAsync({
        subject_type: current.subjectType,
        target_id: current.targetId,
        description: description.trim(),
      });
      setSent(true);
      setOpen(false);
      setDescription('');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.complaints.submitError);
    }
  };

  const sheet = (
    <Sheet
      open={open}
      title={strings.complaints.sheetTitle}
      onClose={() => setOpen(false)}
      locked={createComplaint.isPending}
      actions={
        <>
          <ActionButton
            loading={createComplaint.isPending}
            disabled={!description.trim()}
            onClick={() => void handleSubmit()}
          >
            {strings.complaints.send}
          </ActionButton>
          <ActionButton
            kind="s"
            disabled={createComplaint.isPending}
            onClick={() => setOpen(false)}
          >
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <List role="radiogroup" aria-label={strings.complaints.typesLabel}>
        {options.map((option) => (
          <ListRow
            key={keyOf(option)}
            title={option.label ?? strings.complaints.typeLabel[option.subjectType]}
            control={{ type: 'radio', checked: keyOf(option) === selected }}
            onToggle={() => setSelected(keyOf(option))}
          />
        ))}
      </List>
      <TextAreaField
        id={`complaint-description-${targetId}`}
        label={strings.complaints.whatHappened}
        value={description}
        onChange={setDescription}
        placeholder={strings.complaints.descriptionPlaceholder}
        rows={3}
        error={error ?? undefined}
      />
      <Note>{strings.complaints.operatorNote}</Note>
    </Sheet>
  );

  if (variant === 'row') {
    return (
      <>
        <ListRow
          title={trigger}
          subtitle={sent ? strings.complaints.sent : undefined}
          action="accent"
          aria-label={trigger}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
        />
        {sheet}
      </>
    );
  }

  if (sent) {
    return <Note role="status">{strings.complaints.sent}</Note>;
  }

  return (
    <>
      <ActionButton
        kind="s"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        {trigger}
      </ActionButton>
      {sheet}
    </>
  );
}
