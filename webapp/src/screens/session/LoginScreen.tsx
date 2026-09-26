import { lazy, Suspense, type ComponentType } from 'react';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { closeApp, isBridgeAvailable } from '../../max/bridge';
import { BottomActions, HeaderBar } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StatusHero } from '../../ui/StatusHero';

let DemoLoginForm: ComponentType | null = null;
if (import.meta.env.VITE_DEMO_LOGIN === 'true') {
  DemoLoginForm = lazy(() => import('./DemoLoginForm'));
}

export function LoginScreen() {
  const { status, loginErrorMessage, retryLogin, openedViaLink } = useSession();
  const inMax = isBridgeAvailable();
  const failed = status === 'login_error';

  const DemoForm = openedViaLink || import.meta.env.VITE_DEMO_LOGIN !== 'true' ? null : DemoLoginForm;
  const canRetry = failed || !DemoForm;

  if (DemoForm && !failed) {
    return (
      <div className="ui-layout">
        <div className="ui-screen">
          <HeaderBar title={strings.ui.appTitle} />
          <div className="ui-screen__body">
            <Suspense fallback={null}>
              <DemoForm />
            </Suspense>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ui-layout">
      <div className="ui-screen">
        <HeaderBar title={strings.ui.appTitle} />
        <div className="ui-screen__body">
          <StatusHero
            illustration={failed ? 'error-maintenance' : 'chat'}
            top={72}
            role="alert"
            title={failed ? strings.session.unavailableTitle : strings.session.outsideMaxTitle}
          >
            {loginErrorMessage ??
              (failed ? strings.session.loginRetryableError : strings.session.outsideMaxText)}
          </StatusHero>
          {DemoForm && (
            <Suspense fallback={null}>
              <DemoForm />
            </Suspense>
          )}
        </div>
        {(canRetry || inMax) && (
          <BottomActions>
            {canRetry && <ActionButton onClick={retryLogin}>{strings.common.retry}</ActionButton>}
            {inMax && (
              <ActionButton kind="s" onClick={closeApp}>
                {strings.session.openBotChat}
              </ActionButton>
            )}
          </BottomActions>
        )}
      </div>
    </div>
  );
}
