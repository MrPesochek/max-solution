import type { ReactNode } from 'react';
import { strings } from '../../../strings/ru';
import type { RequestRoute, ServiceBinding, Urgency } from '../../../api/types';
import { Banner, PageTitle } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';

const t = strings.requests.wizard;

interface ReviewStepProps {
  route: RequestRoute;
  isEmployee: boolean;
  approverName?: string | null;
  binding: ServiceBinding | null;
  equipmentTitle: string;
  locationName: string | undefined;
  urgency: Urgency;
  errorCode: string;
  symptomDescription: string;
  photosValue: string;
  onEdit: () => void;
  noPhotoReason: string | null;
  hasUnresolvedSlots: boolean;
  isUrgent: boolean;
  confirmIncomplete: boolean;
  onConfirmIncompleteChange: (value: boolean) => void;
}

function SummaryRow({
  label,
  value,
  hint,
  onEdit,
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  onEdit?: () => void;
}) {
  return (
    <li className="wizard-summary__row">
      <div className="wizard-summary__main">
        <span className="wizard-summary__key">{label}</span>
        <span className="wizard-summary__value">{value}</span>
        {hint && <span className="wizard-summary__hint">{hint}</span>}
      </div>
      {onEdit && (
        <button
          type="button"
          className="wizard-summary__edit"
          aria-label={t.reviewEditLabel(label, value)}
          onClick={onEdit}
        >
          {t.reviewEdit}
        </button>
      )}
    </li>
  );
}

export function ReviewStep({
  route,
  isEmployee,
  approverName,
  binding,
  equipmentTitle,
  locationName,
  urgency,
  errorCode,
  symptomDescription,
  photosValue,
  onEdit,
  noPhotoReason,
  hasUnresolvedSlots,
  isUrgent,
  confirmIncomplete,
  onConfirmIncompleteChange,
}: ReviewStepProps) {
  const recipient =
    route === 'own_service'
      ? binding
        ? t.reviewRecipientOwn(
            binding.provider.name,
            t.reviewRecipientBasis[binding.basis] ?? t.reviewRecipientBasis.preferred!,
          )
        : strings.common.notSpecified
      : isEmployee
        ? t.reviewRecipientApproval
        : t.reviewRecipientMarketplace;

  return (
    <>
      <PageTitle>{t.reviewTitle}</PageTitle>

      <ul className="wizard-summary">
        <SummaryRow
          label={t.reviewEquipment}
          value={t.reviewEquipmentValue(equipmentTitle, locationName)}
          onEdit={onEdit}
        />
        <SummaryRow label={t.reviewRecipient} value={recipient} />
        <SummaryRow
          label={t.reviewProblem}
          value={symptomDescription.trim() || t.reviewNoSymptoms}
          hint={errorCode.trim() ? `${t.reviewErrorCode}: ${errorCode.trim()}` : undefined}
          onEdit={onEdit}
        />
        <SummaryRow
          label={t.reviewPhotos}
          value={photosValue}
          hint={noPhotoReason ? t.reviewNoPhotoReason(noPhotoReason) : undefined}
          onEdit={onEdit}
        />
        <SummaryRow label={t.reviewWhen} value={t.urgencyShort[urgency]} onEdit={onEdit} />
      </ul>

      {route === 'marketplace' &&
        (isEmployee ? (
          <Banner title={t.reviewApprovalTitle} tone="a">
            {t.reviewApprovalText(approverName)}
          </Banner>
        ) : (
          <Banner title={t.reviewMarketplaceTitle} tone="a">
            {t.reviewMarketplaceText}
          </Banner>
        ))}

      {hasUnresolvedSlots && (
        <>
          <Banner
            title={t.photosIncompleteTitle}
            tone={isUrgent ? 'y' : 'x'}
            role={isUrgent ? undefined : 'alert'}
          >
            {isUrgent ? t.photosIncompleteUrgentNotice : t.photosIncompleteNotice}
          </Banner>
          {isUrgent && (
            <List>
              <ListRow
                title={t.photosIncompleteConfirm}
                control={{ type: 'checkbox', checked: confirmIncomplete }}
                onToggle={onConfirmIncompleteChange}
              />
            </List>
          )}
        </>
      )}

      {route === 'own_service' && binding && (
        <p className="wizard-footnote">{t.reviewOnlyProvider(binding.provider.name)}</p>
      )}
    </>
  );
}
