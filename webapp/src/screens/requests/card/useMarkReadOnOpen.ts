import { useEffect, useRef } from 'react';
import { useMarkMessagesRead, useRequestMessages } from '../../../api/hooks/useRequests';

export function useMarkReadOnOpen(id: string | undefined): void {
  const messages = useRequestMessages(id, Boolean(id));
  const markRead = useMarkMessagesRead(id);
  const mutate = useRef(markRead.mutate);
  mutate.current = markRead.mutate;
  const lastMarked = useRef<string | null>(null);

  const count = messages.data?.length;
  useEffect(() => {
    if (!id || count === undefined) return;
    const mark = `${id}:${count}`;
    if (lastMarked.current === mark) return;
    lastMarked.current = mark;
    mutate.current();
  }, [id, count]);
}
