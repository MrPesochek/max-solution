import { Illustration, equipmentIllustration } from './illustrations';

export function EquipmentIcon({
  code,
  name,
  width = 52,
  alt,
}: {
  code?: string | null;
  name?: string | null;
  width?: number;
  alt?: string;
}) {
  return <Illustration name={equipmentIllustration(code, name)} width={width} alt={alt} />;
}
