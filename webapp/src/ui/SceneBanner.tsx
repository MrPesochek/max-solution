import type { ReactNode } from 'react';
import { Illustration, type IllustrationName } from './illustrations';

interface SceneBannerProps {
  name: IllustrationName;
  height?: number;
  width?: number;
  align?: 'bottom' | 'center';
  alt?: string;
  children?: ReactNode;
  className?: string;
}

export function SceneBanner({
  name,
  height = 150,
  width,
  align = 'bottom',
  alt,
  children,
  className,
}: SceneBannerProps) {
  const imageWidth = width ?? Math.round(height * 1.25);
  const large = height >= 170;
  return (
    <div
      className={['ui-scene', `ui-scene--${align}`, large && 'ui-scene--large', className].filter(Boolean).join(' ')}
      style={{ height }}
    >
      <Illustration name={name} width={imageWidth} alt={alt} className="ui-scene__img" />
      {children}
    </div>
  );
}
