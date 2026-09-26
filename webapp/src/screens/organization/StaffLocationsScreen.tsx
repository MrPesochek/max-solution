import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useLocations } from '../../api/hooks/useLocations';
import { useSetMembershipLocations, useStaff } from '../../api/hooks/useMemberships';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { EmptyState } from '../../components/states/EmptyState';
import { useSession } from '../../session/SessionContext';
import { canEditMembershipLocations } from '../../lib/roles';
import { Banner, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';

export function StaffLocationsScreen() {
  const { membershipId } = useParams<{ membershipId: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const staff = useStaff();
  const locations = useLocations();
  const setLocations = useSetMembershipLocations(membershipId ?? '');

  const [selected, setSelected] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const member = staff.data?.find((m) => m.id === membershipId);

  useEffect(() => {
    if (member) setSelected(member.location_ids);
  }, [member]);

  if (!activeMembership || !membershipId) return null;
  const frame = (body: ReactNode) => (
    <Screen title={strings.organization.editLocations}>{body}</Screen>
  );
  if (!canEditMembershipLocations(activeMembership.role)) return frame(<NoAccessState />);

  if (staff.isPending || locations.isPending) return frame(<Skeleton lines={5} />);
  if (staff.isError)
    return frame(<ErrorState error={staff.error} onRetry={() => void staff.refetch()} />);
  if (locations.isError) {
    return frame(<ErrorState error={locations.error} onRetry={() => void locations.refetch()} />);
  }
  if (!member) return frame(<EmptyState title={strings.states.empty} />);

  const toggle = (locationId: string, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...prev, locationId] : prev.filter((id) => id !== locationId),
    );
  };

  const handleSave = async () => {
    setFormError(null);
    try {
      await setLocations.mutateAsync(selected);
      navigate('/organization/staff', { replace: true });
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  return (
    <Screen
      title={member.user.display_name}
      subtitle={strings.home.roleShort[member.role]}
      actions={
        locations.data.length > 0 ? (
          <BottomActions>
            <ActionButton loading={setLocations.isPending} onClick={() => void handleSave()}>
              {strings.common.save}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      {locations.data.length === 0 ? (
        <EmptyState title={strings.locations.empty} />
      ) : (
        <>
          <SectionCaption>{strings.organization.locationsAccess}</SectionCaption>
          <List role="group" aria-label={strings.organization.locationsAccess}>
            {locations.data.map((location) => (
              <ListRow
                key={location.id}
                title={location.name}
                subtitle={location.address}
                control={{ type: 'checkbox', checked: selected.includes(location.id) }}
                onToggle={(next) => toggle(location.id, next)}
              />
            ))}
          </List>
        </>
      )}
      {formError && <Banner tone="x" role="alert" title={formError} />}
    </Screen>
  );
}
