export function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="detail-info-row">
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
