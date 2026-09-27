import type { Delivery } from '../../api/types';

export function needsRedelivery(delivery: Delivery): boolean {
  return delivery.state === 'failed' || delivery.state === 'blocked';
}
