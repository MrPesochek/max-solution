import { useQuery } from '@tanstack/react-query';
import { operatorApi } from '../client';
import { ApiError } from '../errors';
import { queryKeys } from '../queryKeys';
import type { Page } from '../types';

export function useOperatorAccess() {
  const query = useQuery({
    queryKey: queryKeys.operatorAccess,
    queryFn: async () => {
      await operatorApi.get<Page<unknown>>('/verification-cases', { query: { limit: 1 } });
      return true;
    },
    retry: false,
    staleTime: Infinity,
    throwOnError: false,
  });

  const retry = () => void query.refetch();
  if (query.isSuccess)
    return { hasAccess: true, isLoading: false, networkError: false, error: null, retry };
  if (query.isError) {
    const denied =
      query.error instanceof ApiError && (query.error.status === 401 || query.error.status === 403);
    return { hasAccess: false, isLoading: false, networkError: !denied, error: query.error, retry };
  }
  return { hasAccess: false, isLoading: true, networkError: false, error: null, retry };
}
