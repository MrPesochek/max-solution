import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

export function useSubView<V extends string>(
  views: readonly V[],
  { clear = [] }: { clear?: readonly string[] } = {},
): [V | 'main', (next: V | 'main') => void] {
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const raw = search.get('view');
  const view: V | 'main' = raw && (views as readonly string[]).includes(raw) ? (raw as V) : 'main';

  const setView = (next: V | 'main') => {
    if (next === view) return;
    if (next === 'main') {
      const state = location.state as { subView?: boolean } | null;
      if (state?.subView) {
        navigate(-1);
        return;
      }
      setSearch(
        (current) => {
          const params = new URLSearchParams(current);
          params.delete('view');
          return params;
        },
        { replace: true },
      );
      return;
    }
    setSearch(
      (current) => {
        const params = new URLSearchParams(current);
        params.set('view', next);
        for (const name of clear) params.delete(name);
        return params;
      },
      { state: { subView: true } },
    );
  };
  return [view, setView];
}
