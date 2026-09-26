import type { SVGProps } from 'react';

type IconName = 'arrow' | 'plus' | 'equipment' | 'check' | 'clock' | 'search' | 'service';
const paths: Record<IconName, string> = {
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  plus: 'M12 5v14M5 12h14',
  equipment: 'M6 3h12v18H6zM6 11h12M9 6v2m0 6v3',
  check: 'm6 12 4 4 8-8',
  clock: 'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  search: 'M20 20l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  service: 'm14 6 4-3a6 6 0 0 1-7 8l-7 7a2 2 0 0 0 3 3l7-7a6 6 0 0 0 7-8l-3 4z',
};
export function AppIcon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={paths[name]} />
    </svg>
  );
}
