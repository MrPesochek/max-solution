import type { LabelHTMLAttributes } from 'react';
import { Typography } from '@maxhub/max-ui';

export function FormLabel(props: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <Typography.Label asChild variant="medium" style={{ display: 'block', marginBottom: 6 }}>
      <label {...props} />
    </Typography.Label>
  );
}
