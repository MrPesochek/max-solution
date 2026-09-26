import { SkeletonRows } from '../../ui/Skeleton';

interface SkeletonProps {
  lines?: number;
}

export function Skeleton({ lines = 3 }: SkeletonProps) {
  return (
    <div className="ui-skeleton">
      <SkeletonRows rows={lines} />
    </div>
  );
}
