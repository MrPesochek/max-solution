import { Link } from 'react-router-dom';
import { strings } from '../../strings/ru';
import type { ServiceBinding } from '../../api/types';
import { Avatar, Banner } from '../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { bindingName, guarantorName, guarantorStated, hasWarranty, serviceState, shortDate } from './bindingView';

function contactLetter(name: string): string {
  const words = name.trim().split(/\s+/);
  const word = words.length > 1 && /^(мастер|master)$/i.test(words[0]!) ? words[1]! : words[0]!;
  return (word.charAt(0) || '?').toUpperCase();
}

function CheckBadge() {
  return (
    <svg className="eq-service__mark" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="currentColor" />
      <path
        d="M7.5 12.5l3 3 6-6.5"
        fill="none"
        stroke="var(--s)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StateLine({ binding }: { binding: ServiceBinding }) {
  if (binding.is_contact_only) {
    return (
      <span className="eq-service__state">
        {[binding.contact_phone, strings.bindings.contactOnlySubtitle].filter(Boolean).join(' · ')}
      </span>
    );
  }
  if (binding.status === 'confirmed') {
    return (
      <span className="eq-service__state">
        <CheckBadge />
        {strings.equipment.serviceState.confirmed}
      </span>
    );
  }
  const text = binding.status === 'pending' ? strings.equipment.serviceState.pending : strings.bindings.statusTag[binding.status];
  return <span className="eq-service__state eq-service__state--warn">{text}</span>;
}

function bindingRows(binding: ServiceBinding, warrantyPath: string): KeyValueRow[] {
  if (binding.is_contact_only) return [];
  const rows: KeyValueRow[] = [
    {
      label: strings.equipment.serviceBasis,
      value: binding.contract_number
        ? strings.bindings.contractShort(binding.contract_number)
        : strings.bindings.basisLabel[binding.basis],
    },
  ];
  if (binding.valid_until) {
    rows.push({ label: strings.equipment.serviceValid, value: strings.bindings.until(shortDate(binding.valid_until)) });
  }
  if (binding.status === 'confirmed' && hasWarranty(binding)) {
    const until = binding.valid_until ?? binding.warranty_authorization?.valid_until ?? null;
    const value = strings.equipment.serviceWarrantyValue(guarantorName(binding), until ? shortDate(until) : null);
    rows.push({
      label: strings.equipment.serviceWarranty,
      hint: guarantorStated(binding) ? strings.bindings.acceptGuarantorHint : undefined,
      value: (
        <Link className="eq-kv-link" to={warrantyPath} aria-label={strings.equipment.serviceWarrantyLink(value)}>
          {value}
        </Link>
      ),
    });
  }
  return rows;
}

export function EquipmentBindingsSection({
  bindings,
  warrantyPath,
}: {
  bindings: ServiceBinding[];
  warrantyPath: string;
}) {
  const visible = bindings
    .filter((b) => b.status !== 'revoked')
    .sort((a, b) => rank(a) - rank(b));
  const state = serviceState(bindings);

  return (
    <section aria-label={strings.equipment.serviceCaption} className="eq-tab-panel">
      {visible.map((binding) => {
        const name = bindingName(binding);
        const head = (
          <>
            <Avatar size={44} name={name} gradient={binding.is_contact_only ? 'n' : 'o'} aria-hidden>
              {binding.is_contact_only ? contactLetter(name) : undefined}
            </Avatar>
            <span className="eq-service__main">
              <span className="eq-service__name">{name}</span>
              <StateLine binding={binding} />
            </span>
          </>
        );
        const rows = bindingRows(binding, warrantyPath);
        return (
          <div key={binding.id} className="eq-service">
            {binding.is_contact_only ? (
              <div className="eq-service__head">{head}</div>
            ) : (
              <Link className="eq-service__head" to="/bindings" aria-label={name}>
                {head}
              </Link>
            )}
            {rows.length > 0 && <KeyValueRows rows={rows} />}
          </div>
        );
      })}
      {state === 'contact' && (
        <Banner tone="y" title={strings.equipment.noServiceTitle}>
          {strings.equipment.noServiceContactText}
        </Banner>
      )}
      {state === 'none' && (
        <Banner tone="y" title={strings.equipment.noServiceTitle}>
          {strings.equipment.noServiceText}
        </Banner>
      )}
    </section>
  );
}

function rank(binding: ServiceBinding): number {
  if (binding.is_contact_only) return 3;
  if (binding.status === 'confirmed') return 0;
  if (binding.status === 'pending') return 1;
  return 2;
}
