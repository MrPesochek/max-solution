import { strings } from '../../strings/ru';
import { closeApp, isBridgeAvailable } from '../../max/bridge';
import { BottomActions, HeaderBar } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StatusHero } from '../../ui/StatusHero';
import { useSession } from '../../session/SessionContext';
import { botChatUrl, openBotChat } from '../../session/loginLink';

export function ReopenRequiredScreen() {
  const { openedViaLink } = useSession();
  const inMax = isBridgeAvailable();
  const toBot = !inMax && openedViaLink && botChatUrl() !== null;
  return (
    <div className="ui-layout">
      <div className="ui-screen">
        <HeaderBar title={strings.ui.appTitle} />
        <div className="ui-screen__body">
          <StatusHero
            illustration="status-waiting"
            top={72}
            title={strings.session.reopenRequired}
            role="alert"
          >
            {openedViaLink && !inMax
              ? strings.session.linkReopenText
              : strings.session.reopenDescription}
          </StatusHero>
        </div>
        {(inMax || toBot) && (
          <BottomActions>
            <ActionButton kind="s" onClick={inMax ? closeApp : openBotChat}>
              {inMax ? strings.session.continueInBot : strings.session.openBotChat}
            </ActionButton>
          </BottomActions>
        )}
      </div>
    </div>
  );
}
