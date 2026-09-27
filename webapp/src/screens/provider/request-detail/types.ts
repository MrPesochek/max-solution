import type { RequestProvider } from '../../../api/types';
import type { ActionRunner } from '../../../components/actions/useActionRunner';
import { equipmentShortName } from '../../requests/components/equipmentName';

export interface ProviderPanelProps {
  request: RequestProvider;
  runner: ActionRunner;
}

export interface ProviderSubViewProps extends ProviderPanelProps {
  onDone: () => void;
}

export async function runAndClose(
  runner: ActionRunner,
  name: string,
  action: () => Promise<unknown>,
  onDone: () => void,
): Promise<void> {
  const ok = await runner.run(name, async () => {
    await action();
    return true;
  });
  if (ok) onDone();
}

export function equipmentTitle(request: RequestProvider): string {
  return equipmentShortName({
    category: request.equipment_category_name ?? request.equipment.category_name,
    brand: request.equipment.brand,
    model: request.equipment.model,
  });
}
