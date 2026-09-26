import { useId, useState } from 'react';
import { strings } from '../../../strings/ru';
import type { RequestCustomer } from '../../../api/types';
import { RequestAttachments } from '../../../components/request/RequestAttachments';
import { EquipmentIcon } from '../../../ui/EquipmentIcon';
import { KeyValueRows, type KeyValueRow } from '../../../ui/KeyValueRows';
import { urgencyLabel } from '../../../lib/status';
import { equipmentName } from './cardFormat';
import { RequestProviderSection } from './RequestProviderSection';

export function CardSubject({
  request,
  canUpload,
  onStale,
  slotLabels,
  showProvider = true,
}: {
  request: RequestCustomer;
  canUpload: boolean;
  onStale: () => unknown;
  slotLabels: Record<string, string>;
  showProvider?: boolean;
}) {
  const c = strings.requests.card;
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const photos = request.attachments.filter((a) => !a.message_id);
  const description = request.symptom_description?.trim();
  const sub = [
    [request.equipment.brand, request.equipment.model].filter(Boolean).join(' ') || null,
    request.location.name,
  ]
    .filter(Boolean)
    .join(' · ');

  const facts: KeyValueRow[] = [
    { label: c.urgencyTitle, value: urgencyLabel(request.urgency) },
    ...(request.error_code ? [{ label: c.errorCodeTitle, value: request.error_code }] : []),
    ...(request.location.address ? [{ label: c.locationTitle, value: request.location.address }] : []),
  ];

  const toggleLabel = open ? c.collapse : photos.length > 0 ? c.expandWithPhotos(photos.length) : c.expand;

  return (
    <section className="request-subject" aria-label={c.detailsCaption}>
      <div className="request-subject__head">
        <div className="request-subject__main">
          <h3 className="request-subject__title">{equipmentName(request)}</h3>
          {sub && <span className="request-subject__sub">{sub}</span>}
        </div>
        <EquipmentIcon name={request.equipment_category_name ?? request.equipment.category_name} width={84} />
      </div>
      {description && (
        <p className={`request-subject__text${open ? '' : ' request-subject__text--clamp'}`}>{description}</p>
      )}
      {open && (
        <div className="request-subject__details" id={detailsId}>
          <RequestAttachments
            requestId={request.id}
            requestNumber={request.request_number}
            attachments={request.attachments}
            canUpload={canUpload}
            onStale={onStale}
            slotLabels={slotLabels}
            hideCaption
          />
          <KeyValueRows rows={facts} />
          {showProvider && request.assignment && <RequestProviderSection request={request} />}
        </div>
      )}
      <button
        type="button"
        className="request-link"
        aria-expanded={open}
        aria-controls={open ? detailsId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {toggleLabel}
      </button>
    </section>
  );
}
