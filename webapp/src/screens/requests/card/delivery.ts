import { strings } from '../../../strings/ru';
import type { RequestCustomer } from '../../../api/types';
import { formatTime } from '../../../lib/datetime';
import type { RowMarker } from '../../../ui/List';

export interface DeliveryStep {
  title: string;
  marker: RowMarker;
  value: string;
  pending: boolean;
}

export type DeliveryProblem = 'retrying' | 'failed';

export function deliveryProblem(request: RequestCustomer): DeliveryProblem | null {
  const delivery = request.delivery;
  if (!delivery || delivery.channel !== 'crm') return null;
  if (delivery.state === 'retrying' || delivery.state === 'failed') return delivery.state;
  return null;
}

export function deliveryStep(request: RequestCustomer): DeliveryStep | null {
  const c = strings.requests.card;
  const delivery = request.delivery;
  const tz = request.location.timezone;
  if (!delivery) return null;
  if (delivery.channel === 'app') {
    const at = request.assignment?.created_at ?? request.submitted_at;
    return { title: c.timelineDeliveredApp, marker: 'ok', value: formatTime(at, tz), pending: false };
  }
  switch (delivery.state) {
    case 'delivered':
      return { title: c.timelineDelivered, marker: 'ok', value: formatTime(delivery.delivered_at, tz), pending: false };
    case 'retrying':
      return { title: c.timelineDelivered, marker: 'x', value: c.timelineRetrying, pending: true };
    case 'failed':
      return { title: c.timelineDelivered, marker: 'x', value: c.timelineFailed, pending: true };
    default:
      return { title: c.timelineDelivered, marker: 'w', value: c.timelineWaiting, pending: true };
  }
}

export function deliveryProblemText(request: RequestCustomer, problem: DeliveryProblem): string {
  const c = strings.requests.card;
  const last = request.delivery?.last_attempt_at;
  const time = last ? formatTime(last, request.location.timezone) : null;
  return problem === 'retrying' ? c.deliveryRetryingText(time) : c.deliveryFailedText(time);
}
