import { strings } from '../../../strings/ru';
import { List, ListRow } from '../../../ui/List';
import { SelectField, TextAreaField, TextField } from '../../../ui/FormField';
import type { PriceFormValue } from '../../../lib/priceForm';
import { VAT_OPTIONS } from './priceText';
import { PriceStepper } from './PriceStepper';

export function PriceForm({
  value,
  onChange,
  idPrefix = 'price',
  amountLabel = strings.workspace.priceAmountLabel,
  allowUnknown = true,
  stepper = false,
}: {
  value: PriceFormValue;
  onChange: (value: PriceFormValue) => void;
  idPrefix?: string;
  amountLabel?: string;
  allowUnknown?: boolean;
  stepper?: boolean;
}) {
  return (
    <>
      {value.mode === 'amount' && stepper && (
        <PriceStepper
          id={`${idPrefix}-amount`}
          label={amountLabel}
          value={value.amountRub}
          onChange={(amountRub) => onChange({ ...value, amountRub })}
        />
      )}
      {value.mode === 'amount' && !stepper && (
        <TextField
          id={`${idPrefix}-amount`}
          label={amountLabel}
          inputMode="decimal"
          placeholder={strings.workspace.priceAmountPlaceholder}
          value={value.amountRub}
          onChange={(amountRub) => onChange({ ...value, amountRub })}
        />
      )}
      <List>
        {allowUnknown && (
          <ListRow
            title={strings.workspace.priceUnknownSwitch}
            control={{ type: 'switch', checked: value.mode === 'unknown' }}
            onToggle={(next) => onChange({ ...value, mode: next ? 'unknown' : 'amount' })}
          />
        )}
        <ListRow
          title={strings.workspace.priceFreeSwitch}
          control={{ type: 'switch', checked: value.mode === 'free' }}
          onToggle={(next) => onChange({ ...value, mode: next ? 'free' : 'amount' })}
        />
      </List>
      {value.mode === 'free' && (
        <TextAreaField
          id={`${idPrefix}-zero-reason`}
          label={strings.workspace.priceZeroReasonLabel}
          value={value.zeroCostReason}
          onChange={(zeroCostReason) => onChange({ ...value, zeroCostReason })}
          rows={2}
        />
      )}
      {value.mode === 'amount' && (
        <SelectField
          id={`${idPrefix}-vat`}
          label={strings.workspace.vatModeLabel}
          value={value.vatMode}
          options={VAT_OPTIONS}
          placeholder={strings.workspace.vatModeNotSet}
          allowEmpty
          onChange={(vatMode) => onChange({ ...value, vatMode })}
        />
      )}
    </>
  );
}
