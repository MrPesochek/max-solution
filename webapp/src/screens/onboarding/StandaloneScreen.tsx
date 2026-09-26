import { Screen, type ScreenProps } from '../../ui/layout/Screen';

export function StandaloneScreen(props: ScreenProps) {
  return (
    <div className="ui-layout">
      <Screen {...props} />
    </div>
  );
}
