import { strings } from '../../strings/ru';
import { BottomActions, HeaderBar } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StatusHero } from '../../ui/StatusHero';
import { botChatUrl, openBotChat } from '../../session/loginLink';

export function LinkInvalidScreen() {
  return (
    <div className="ui-layout">
      <div className="ui-screen">
        <HeaderBar title={strings.ui.appTitle} />
        <div className="ui-screen__body">
          <StatusHero
            illustration="status-waiting"
            top={72}
            title={strings.session.linkInvalidTitle}
            role="alert"
          >
            {strings.session.linkInvalidText}
          </StatusHero>
        </div>
        {botChatUrl() !== null && (
          <BottomActions>
            <ActionButton onClick={openBotChat}>{strings.session.openBotChat}</ActionButton>
          </BottomActions>
        )}
      </div>
    </div>
  );
}
