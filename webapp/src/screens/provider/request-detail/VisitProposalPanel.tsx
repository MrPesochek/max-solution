import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useProposeVisit } from '../../../api/hooks/useProviderRequests';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import {
  EMPTY_PRICE_VALUE,
  isPriceValueValid,
  priceValueToBody,
  type PriceFormValue,
} from '../../../lib/priceForm';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note, SectionCaption } from '../../../ui/blocks/Blocks';
import { TextAreaField, TextField } from '../../../ui/FormField';
import { PriceForm } from '../components/PriceForm';
import { localToIso } from '../components/priceText';
import { runAndClose, type ProviderSubViewProps } from './types';

export function VisitProposalPanel({ request, runner, onDone }: ProviderSubViewProps) {
  const proposeVisit = useProposeVisit(request.id);
  const [price, setPrice] = useState<PriceFormValue>({ ...EMPTY_PRICE_VALUE, mode: 'amount' });
  const [visitStart, setVisitStart] = useState('');
  const [visitEnd, setVisitEnd] = useState('');
  const [scope, setScope] = useState('');
  const [comment, setComment] = useState('');
  const [access, setAccess] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const approved = request.visit_proposals.some((v) => v.status === 'approved');

  const submit = () =>
    runAndClose(
      runner,
      'proposeVisit',
      () =>
        proposeVisit.mutateAsync({
          assignment_id: request.assignment.id,
          visit_window_start: localToIso(visitStart),
          visit_window_end: localToIso(visitEnd),
          ...priceValueToBody(price),
          scope_description: scope.trim() || null,
          comment: comment.trim() || null,
          access_requirements: access.trim() || null,
          valid_until: localToIso(validUntil),
          expected_version: request.version,
        }),
      onDone,
    );

  return (
    <Screen
      title={
        approved ? strings.workspace.actionChangeTime : strings.workspace.visitProposalFormTitle
      }
      subtitle={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('proposeVisit')}
            disabled={!isPriceValueValid(price) || runner.busy}
            onClick={() => void submit()}
          >
            {strings.workspace.sendForApproval}
          </ActionButton>
        </BottomActions>
      }
    >
      {approved && <Note>{strings.workspace.actionChangeVisitWarning}</Note>}
      <TextField
        id="visit-start"
        type="datetime-local"
        label={strings.workspace.offerWindowStartLabel}
        value={visitStart}
        onChange={setVisitStart}
      />
      <TextField
        id="visit-end"
        type="datetime-local"
        label={strings.workspace.offerWindowEndLabel}
        hint={strings.workspace.offerTimezoneHintWith(request.location.timezone)}
        value={visitEnd}
        onChange={setVisitEnd}
      />
      <PriceForm
        idPrefix="visit-price"
        amountLabel={strings.workspace.offerPriceLabel}
        value={price}
        onChange={setPrice}
      />
      <TextAreaField
        id="visit-scope"
        label={strings.offers.scopeLabel}
        placeholder={strings.workspace.offerScopePlaceholder}
        value={scope}
        onChange={setScope}
        rows={2}
      />
      <TextField
        id="visit-valid-until"
        type="datetime-local"
        label={strings.workspace.offerValidUntilScreenLabel}
        value={validUntil}
        onChange={setValidUntil}
      />
      <SectionCaption>{strings.workspace.extraCaption}</SectionCaption>
      <TextAreaField
        id="visit-access"
        label={strings.workspace.offerAccessRequirementsLabel}
        value={access}
        onChange={setAccess}
        rows={2}
      />
      <TextAreaField
        id="visit-comment"
        label={strings.offers.commentLabel}
        value={comment}
        onChange={setComment}
        rows={2}
      />
      <ActionFeedback feedback={runner.feedback} />
    </Screen>
  );
}
