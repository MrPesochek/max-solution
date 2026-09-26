import type { ReactNode } from 'react';
import type { Tone } from '../lib/trust';
import { Tag, type Tone as TagTone } from '../ui/blocks/Blocks';

const TAG_TONE: Record<Tone, TagTone> = {
  neutral: 'w',
  positive: 'ok',
  warning: 'y',
  negative: 'x',
};

interface StatusBadgeProps {
  label: ReactNode;
  tone: Tone;
}

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return <Tag tone={TAG_TONE[tone]}>{label}</Tag>;
}
