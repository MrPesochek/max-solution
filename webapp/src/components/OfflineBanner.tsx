import { strings } from '../strings/ru';
import { useOnlineStatus } from '../lib/useOnlineStatus';

export function OfflineBanner() {
  const online = useOnlineStatus();
  if (online) return null;
  return (
    <div className="ui-offline" role="status">
      {strings.states.offline}
    </div>
  );
}
