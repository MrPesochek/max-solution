import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import { strings } from '../../strings/ru';
import { useRefreshRequest, useSelectOffer } from '../../api/hooks/useRequests';
import { ApiError } from '../../api/errors';
import type { Offer, RequestCustomer } from '../../api/types';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { formatPrice, isPriceKnown, vatModeLabel } from '../../lib/money';
import { Note } from '../../ui/blocks/Blocks';
import { relativeWindow } from '../requests/card/cardFormat';
import { ActionButton } from '../../ui/layout/ActionButton';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { Sheet } from '../../ui/Sheet';

const OFFER_STALE_CODES: ReadonlySet<string> = new Set(['OFFER_EXPIRED', 'OFFER_NOT_ACTIVE', 'OFFER_NOT_CURRENT']);

export function useOfferSelection(request: RequestCustomer | null, offersQuery: UseQueryResult<Offer[]>) {
  const navigate = useNavigate();
  const requestId = request?.id ?? '';
  const selectOffer = useSelectOffer(requestId);
  const refresh = useRefreshRequest(request?.id);
  const runner = useActionRunner({
    onStale: refresh,
    staleCodes: OFFER_STALE_CODES,
    fallbackMessage: strings.offers.selectError,
  });
  const [confirming, setConfirming] = useState<Offer | null>(null);

  const handleSelect = async (offer: Offer) => {
    if (!request) return;
    let notCurrent = false;
    const selected = await runner.run(
      'select',
      () =>
        selectOffer.mutateAsync({
          offer_id: offer.id,
          offer_version: offer.version,
          expected_version: request.version,
        }),
      {
        mapError: (e) => {
          if (!(e instanceof ApiError)) return null;
          if (e.code === 'OFFER_EXPIRED') return strings.offers.selectExpiredError;
          if (e.code === 'OFFER_NOT_CURRENT') {
            notCurrent = true;
            return strings.offers.offerNotCurrent;
          }
          return null;
        },
      },
    );
    if (selected) {
      navigate(`/requests/${requestId}`, { replace: true });
      return;
    }
    if (notCurrent) {
      const fresh = await offersQuery.refetch();
      const current = fresh.data?.find(
        (o) => o.provider_organization_id === offer.provider_organization_id && o.state === 'active',
      );
      if (current && current.id !== offer.id) {
        setConfirming(current);
        navigate(`/requests/${requestId}/offers/${current.id}`, { replace: true });
        return;
      }
    }
    setConfirming(null);
  };

  const offer = confirming;
  const known = offer ? isPriceKnown(offer.price) : false;
  const sheet = (
    <Sheet
      open={Boolean(offer)}
      role="alertdialog"
      title={strings.offers.selectConfirmTitle}
      description={strings.offers.selectConfirmDescription}
      onClose={() => setConfirming(null)}
      locked={runner.busy}
      actions={
        <>
          <ActionButton
            loading={runner.isRunning('select')}
            disabled={runner.busy}
            onClick={() => offer && void handleSelect(offer)}
          >
            {strings.offers.selectConfirmSubmit}
          </ActionButton>
          <ActionButton kind="s" disabled={runner.busy} onClick={() => setConfirming(null)}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      {offer && (
        <>
          <KeyValueRows
            rows={[
              { label: strings.offers.providerLabel, value: offer.provider?.display_name ?? strings.offers.providerFallback },
              {
                label: strings.offers.whenLabel,
                value: offer.visit_window_start
                  ? relativeWindow(offer.visit_window_start, offer.visit_window_end, request?.location.timezone, true)
                  : strings.offers.visitWindowUnknown,
              },
              { label: strings.offers.scopeLabel, value: offer.scope_description ?? strings.offers.defaultScope },
              { label: strings.offers.priceLabel, value: known ? formatPrice(offer.price) : strings.offers.priceUnknownTitle },
              ...(known ? [{ label: strings.offers.vatLabel, value: vatModeLabel(offer.price.vat_mode) }] : []),
            ]}
          />
          {offer.visit_window_start && known && <Note>{strings.offers.selectConfirmScheduled}</Note>}
        </>
      )}
      <ActionFeedback feedback={runner.feedback} />
    </Sheet>
  );

  return { runner, confirming: Boolean(confirming), confirm: setConfirming, sheet };
}
