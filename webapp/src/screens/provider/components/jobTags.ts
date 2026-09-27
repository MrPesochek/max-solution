import { strings } from '../../../strings/ru';
import type { RequestListItem } from '../../../api/types';
import { equipmentIllustration } from '../../../ui/illustrations';
import type { JobTagTone } from './JobCard';

export function urgencyTag(urgency: string): { label: string; tone: JobTagTone } {
  return {
    label: strings.workspace.jobUrgencyTag[urgency] ?? strings.workspace.jobUrgencyTag.normal!,
    tone: urgency === 'critical' ? 'x' : 'w',
  };
}

export function itemArt(item: RequestListItem) {
  return equipmentIllustration(null, item.equipment_category_name ?? item.equipment_title);
}
