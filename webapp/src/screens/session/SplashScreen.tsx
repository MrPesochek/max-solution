import { strings } from '../../strings/ru';
import { HeaderBar } from '../../ui/layout/Screen';
import { StatusHero } from '../../ui/StatusHero';

export function SplashScreen() {
  return (
    <div className="ui-layout">
      <div className="ui-screen">
        <HeaderBar title={strings.ui.appTitle} />
        <StatusHero
          illustration="welcome-handshake"
          top={120}
          title={strings.session.checkingTitle}
          role="status"
        >
          {strings.session.checkingText}
        </StatusHero>
      </div>
    </div>
  );
}
