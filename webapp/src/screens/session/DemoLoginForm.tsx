import { useState, type FormEvent } from 'react';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { Banner, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { TextField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import type { Gradient } from '../../ui/blocks/Blocks';

interface DemoUser {
  key: string;
  role: string;
  gradient: Gradient;
}

const MOCK_USERS: DemoUser[] = [
  { key: 'customer_manager', role: strings.roles.customer_manager, gradient: 'o' },
  { key: 'customer_employee', role: strings.roles.customer_employee, gradient: 'b' },
  { key: 'provider_admin', role: strings.roles.provider_admin, gradient: 'g' },
  { key: 'provider_active_admin', role: strings.roles.provider_admin, gradient: 'g' },
  { key: 'provider_dispatcher', role: strings.roles.provider_dispatcher, gradient: 'r' },
  {
    key: 'dual_manager',
    role: `${strings.orgPicker.side.customer} + ${strings.orgPicker.side.provider}`,
    gradient: 'p',
  },
  { key: 'operator', role: strings.operator.navLabel, gradient: 'n' },
  { key: 'new_user', role: strings.orgPicker.noOrganizations, gradient: 'n' },
];

const SERVER_USERS: DemoUser[] = [
  { key: 'manager', role: strings.roles.customer_manager, gradient: 'o' },
  { key: 'employee', role: strings.roles.customer_employee, gradient: 'b' },
  { key: 'bakery_manager', role: strings.roles.customer_manager, gradient: 'r' },
  { key: 'provider_admin', role: strings.roles.provider_admin, gradient: 'g' },
  { key: 'provider_dispatcher', role: strings.roles.provider_dispatcher, gradient: 'r' },
  { key: 'ext_provider_1', role: strings.roles.provider_admin, gradient: 'b' },
  { key: 'ext_provider_3', role: strings.roles.provider_admin, gradient: 'p' },
  { key: 'ext_provider_4', role: strings.roles.provider_admin, gradient: 'g' },
  {
    key: 'dual_manager',
    role: `${strings.orgPicker.side.customer} + ${strings.orgPicker.side.provider}`,
    gradient: 'p',
  },
  { key: 'operator', role: strings.operator.navLabel, gradient: 'n' },
];

const USERS = import.meta.env.VITE_USE_MOCKS === 'true' ? MOCK_USERS : SERVER_USERS;

export default function DemoLoginForm() {
  const { loginDemo, loginErrorMessage } = useSession();
  const [userKey, setUserKey] = useState('');
  const [submitting, setSubmitting] = useState<string | null>(null);

  const login = async (key: string) => {
    if (!key || submitting) return;
    setSubmitting(key);
    try {
      await loginDemo(key);
    } finally {
      setSubmitting(null);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void login(userKey.trim());
  };

  return (
    <>
      <PageTitle subtitle={strings.session.demoLoginSubtitle}>
        {strings.session.demoLoginTitle}
      </PageTitle>
      {loginErrorMessage && <Banner tone="x" role="alert" title={loginErrorMessage} />}

      <SectionCaption>{strings.session.demoUsersCaption}</SectionCaption>
      <List>
        {USERS.map((item) => (
          <ListRow
            key={item.key}
            title={item.key}
            subtitle={item.role}
            icon={item.key.slice(0, 1).toUpperCase()}
            gradient={item.gradient}
            chevron
            loading={submitting === item.key}
            disabled={submitting !== null}
            onClick={() => void login(item.key)}
          />
        ))}
      </List>

      <SectionCaption>{strings.session.demoOtherCaption}</SectionCaption>
      <form onSubmit={handleSubmit}>
        <TextField
          id="demo-user-key"
          label={strings.session.demoUserKeyLabel}
          value={userKey}
          onChange={setUserKey}
          placeholder="customer_manager"
          autoCapitalize="none"
          autoCorrect="off"
        />
        <div className="ui-pad">
          <ActionButton
            type="submit"
            kind="s"
            disabled={!userKey.trim()}
            loading={submitting === userKey.trim()}
          >
            {strings.session.demoLoginButton}
          </ActionButton>
        </div>
      </form>
    </>
  );
}
