import { strings } from '../../../strings/ru';
import type { RequestProvider } from '../../../api/types';
import { List, ListRow } from '../../../ui/List';

export function ContactRows({ request }: { request: RequestProvider }) {
  const { location } = request;
  if (!request.contacts_disclosed) return null;
  return (
    <List>
      {location.name && (
        <ListRow title={strings.workspace.detailLocationLabel} value={location.name} />
      )}
      {location.address && (
        <ListRow title={strings.workspace.detailAddressLabel} value={location.address} />
      )}
      <ContactRow request={request} />
    </List>
  );
}

export function ContactRow({ request }: { request: RequestProvider }) {
  const { location } = request;
  if (!request.contacts_disclosed || !(location.contact_phone || location.contact_name))
    return null;
  return (
    <ListRow
      title={strings.workspace.detailContactRow}
      subtitle={location.contact_phone ? location.contact_name : undefined}
      value={location.contact_phone ?? location.contact_name}
      valueTone={location.contact_phone ? 'accent' : undefined}
      href={
        location.contact_phone ? `tel:${location.contact_phone.replace(/[^\d+]/g, '')}` : undefined
      }
    />
  );
}
