import { strings } from '../../strings/ru';
import type { Equipment, RequestStatus } from '../../api/types';
import { requestNo } from '../../ui/format';
import { equipmentTitle } from '../requests/components/equipmentName';
import { bindingSummary } from '../requests/components/equipmentService';

export function equipmentDisplayName(item: Equipment): string {
  return equipmentTitle(item);
}

const NOT_IN_WORK = new Set<RequestStatus>(['draft', 'closed', 'cancelled']);

export type EquipmentLineTone = 'accent' | 'warn' | 'plain';

export interface EquipmentLine {
  text: string;
  tone: EquipmentLineTone;
}

export function equipmentLine(item: Equipment): EquipmentLine {
  const request = item.active_request;
  if (request && !NOT_IN_WORK.has(request.status as RequestStatus)) {
    const state = (strings.requests.tag as Record<string, string>)[request.status] ?? '';
    return { text: strings.equipment.listStatus.activeRequest(state, requestNo(request.request_number)), tone: 'accent' };
  }
  const summary = bindingSummary(item);
  return { text: summary.text, tone: summary.tone };
}
