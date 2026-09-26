import type { CSSProperties } from 'react';
import { strings } from '../strings/ru';

export function SkeletonBlock({
  width = '100%',
  height = 14,
  radius = 8,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return <span className="ui-skel" style={{ width, height, borderRadius: radius, ...style }} aria-hidden="true" />;
}

export function SkeletonRows({
  rows = 4,
  media = true,
  label = strings.common.loading,
}: {
  rows?: number;
  media?: boolean;
  label?: string;
}) {
  return (
    <div className="ui-skel-rows" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="ui-skel-rows__row">
          {media && <SkeletonBlock width={52} height={45} radius={12} />}
          <span className="ui-skel-rows__text">
            <SkeletonBlock width="70%" height={14} />
            <SkeletonBlock width="45%" height={12} />
          </span>
        </div>
      ))}
    </div>
  );
}
