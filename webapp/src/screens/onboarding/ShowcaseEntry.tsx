import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import type { Membership } from '../../api/types';
import { useSession } from '../../session/SessionContext';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { ActionButton } from '../../ui/layout/ActionButton';
import './onboarding.css';
import { Note } from '../../ui/blocks/Blocks';

export function ShowcaseEntry() {
  const { activateMembership, refreshMemberships } = useSession();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ['showcase'],
    queryFn: () => api.get<{ enabled: boolean }>('/showcase', { withoutOrganization: true }),
    retry: false,
  });
  if (!status.data?.enabled) return null;

  const enter = async (side: 'customer' | 'provider') => {
    setBusy(true);
    setError(null);
    try {
      const membership = await api.post<Membership>('/showcase/join', { side }, { withoutOrganization: true });
      if (membership.status !== 'active') {
        setError('Доступ к демонстрации отозван. Обратитесь к организатору стенда.');
        return;
      }
      await refreshMemberships();
      activateMembership(membership);
      navigate('/', { replace: true });
    } catch (e) {
      setError(actionErrorMessage(e, 'Не удалось открыть демонстрацию'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="onb-showcase" aria-label="Демонстрация">
      <Note>Демо-доступ: техника, заявки и исполнители. Изменения видны всем участникам.</Note>
      <ActionButton disabled={busy} onClick={() => void enter('customer')}>Демо: я заказчик</ActionButton>
      <ActionButton disabled={busy} onClick={() => void enter('provider')}>Демо: я исполнитель</ActionButton>
      <ActionButton disabled={busy} to="/showcase/operator">Демо: оператор</ActionButton>
      {error && <Note tone="error" role="alert">{error}</Note>}
    </section>
  );
}
