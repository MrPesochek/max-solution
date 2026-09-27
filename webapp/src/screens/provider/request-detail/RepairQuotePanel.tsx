import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useCreateRepairQuote } from '../../../api/hooks/useProviderRequests';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { parsePositiveRub } from '../../../lib/priceForm';
import { formatAmountMinor } from '../../../lib/money';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { PriceBlock } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { Sheet } from '../../../ui/Sheet';
import { SelectField, TextAreaField, TextField } from '../../../ui/FormField';
import { VAT_OPTIONS, localToIso } from '../components/priceText';
import { runAndClose, type ProviderSubViewProps } from './types';

interface QuoteLine {
  title: string;
  amountMinor: number | null;
}

function describeWork(lines: QuoteLine[], note: string): string {
  return note.trim() || lines.map((line) => line.title).join(', ');
}

export function RepairQuotePanel({ request, runner, onDone }: ProviderSubViewProps) {
  const createQuote = useCreateRepairQuote(request.id);
  const [lines, setLines] = useState<QuoteLine[]>([]);
  const [note, setNote] = useState('');
  const [warranty, setWarranty] = useState(false);
  const [zeroReason, setZeroReason] = useState('');
  const [vatMode, setVatMode] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [lineTitle, setLineTitle] = useState('');
  const [lineAmount, setLineAmount] = useState('');

  const total = lines.reduce((sum, line) => sum + (line.amountMinor ?? 0), 0);
  const description = describeWork(lines, note);
  const valid = description.length > 0 && (warranty ? zeroReason.trim().length > 0 : total > 0);
  const items = lines.map((line) => ({
    title: line.title,
    amount_minor: warranty ? 0 : (line.amountMinor ?? 0),
  }));

  const openLine = (index: number) => {
    const line = index >= 0 ? lines[index] : undefined;
    setLineTitle(line?.title ?? '');
    setLineAmount(line?.amountMinor ? String(line.amountMinor / 100) : '');
    setEditing(index);
  };

  const saveLine = () => {
    const line: QuoteLine = { title: lineTitle.trim(), amountMinor: parsePositiveRub(lineAmount) };
    setLines((current) =>
      editing === null || editing < 0
        ? [...current, line]
        : current.map((item, index) => (index === editing ? line : item)),
    );
    setEditing(null);
  };

  const removeLine = () => {
    setLines((current) => current.filter((_, index) => index !== editing));
    setEditing(null);
  };

  const submit = () =>
    runAndClose(
      runner,
      'createQuote',
      () =>
        createQuote.mutateAsync({
          assignment_id: request.assignment.id,
          description_of_work: description,
          items: items.length > 0 ? items : null,
          amount_minor: warranty ? 0 : total,
          currency: 'RUB',
          vat_mode: warranty ? null : vatMode || null,
          zero_cost_reason: warranty ? zeroReason.trim() : null,
          valid_until: localToIso(validUntil),
          expected_version: request.version,
        }),
      onDone,
    );

  const lineValid = lineTitle.trim().length > 0 && (warranty || parsePositiveRub(lineAmount) !== null);

  return (
    <Screen
      title={strings.workspace.quoteScreenTitle}
      subtitle={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('createQuote')}
            disabled={!valid || runner.busy}
            onClick={() => void submit()}
          >
            {strings.workspace.sendForApproval}
          </ActionButton>
        </BottomActions>
      }
    >
      <List aria-label={strings.workspace.quoteLinesLabel}>
        {lines.map((line, index) => (
          <ListRow
            key={`${line.title}-${index}`}
            title={line.title}
            value={line.amountMinor === null ? '—' : formatAmountMinor(line.amountMinor)}
            aria-label={strings.workspace.quoteLineEdit(line.title)}
            onClick={() => openLine(index)}
          />
        ))}
        <ListRow
          title={strings.workspace.quoteAddLine}
          action="accent"
          onClick={() => openLine(-1)}
        />
      </List>

      <PriceBlock
        value={formatAmountMinor(warranty ? 0 : total)}
        caption={strings.workspace.quoteTotalCaption}
      />

      <List>
        <ListRow
          title={strings.workspace.quoteWarrantySwitch}
          control={{ type: 'switch', checked: warranty }}
          onToggle={setWarranty}
        />
      </List>
      {warranty ? (
        <TextAreaField
          id="quote-zero-reason"
          label={strings.workspace.priceZeroReasonLabel}
          placeholder={strings.workspace.quoteWarrantyReasonPlaceholder}
          value={zeroReason}
          onChange={setZeroReason}
          rows={2}
        />
      ) : (
        <SelectField
          id="quote-vat"
          label={strings.workspace.vatModeLabel}
          value={vatMode}
          options={VAT_OPTIONS}
          placeholder={strings.workspace.vatModeNotSet}
          allowEmpty
          onChange={setVatMode}
        />
      )}
      <TextAreaField
        id="quote-desc"
        label={strings.workspace.quoteNoteLabel}
        placeholder={strings.workspace.quoteNotePlaceholder}
        value={note}
        onChange={setNote}
        rows={2}
      />
      <TextField
        id="quote-valid-until"
        type="datetime-local"
        label={strings.workspace.offerValidUntilLabel}
        value={validUntil}
        onChange={setValidUntil}
      />
      <ActionFeedback feedback={runner.feedback} />

      <Sheet
        open={editing !== null}
        title={
          editing !== null && editing >= 0
            ? strings.workspace.quoteLineEditTitle
            : strings.workspace.quoteAddLine
        }
        onClose={() => setEditing(null)}
        actions={
          <>
            <ActionButton disabled={!lineValid} onClick={saveLine}>
              {editing !== null && editing >= 0
                ? strings.common.save
                : strings.workspace.quoteLineAdd}
            </ActionButton>
            {editing !== null && editing >= 0 ? (
              <ActionButton kind="d" onClick={removeLine}>
                {strings.workspace.quoteLineRemove}
              </ActionButton>
            ) : (
              <ActionButton kind="s" onClick={() => setEditing(null)}>
                {strings.common.cancel}
              </ActionButton>
            )}
          </>
        }
      >
        <TextField
          id="quote-line-title"
          label={strings.workspace.quoteLineTitleLabel}
          placeholder={strings.workspace.quoteLineTitlePlaceholder}
          value={lineTitle}
          onChange={setLineTitle}
        />
        <TextField
          id="quote-line-amount"
          label={strings.workspace.priceAmountLabel}
          inputMode="decimal"
          hint={warranty ? strings.workspace.quoteLineAmountWarrantyHint : undefined}
          value={lineAmount}
          onChange={setLineAmount}
        />
      </Sheet>
    </Screen>
  );
}
