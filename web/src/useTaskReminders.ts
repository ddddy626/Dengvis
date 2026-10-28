import { useEffect, useRef, useState } from 'react';
import { fetchLifeItems, GuestSession } from './api';

export type DueReminder = { key: string; title: string; at: string; kind: 'task' | 'schedule' };

export function useTaskReminders(session: GuestSession | null) {
  const [queue, setQueue] = useState<DueReminder[]>([]);
  const [issue, setIssue] = useState('');
  const acknowledged = useRef(new Set<string>());

  useEffect(() => {
    setQueue([]);
    setIssue('');
    if (!session) return;
    let cancelled = false;
    let fetching = false;
    const check = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const items = await fetchLifeItems(session.token);
        if (cancelled) return;
        const candidates = [
          ...items.tasks.filter((item) => item.status === 'open' && item.dueAt).map((item) => ({ kind: 'task' as const, id: item.id, title: item.title, at: item.dueAt! })),
          ...items.schedules.filter((item) => item.status === 'planned').map((item) => ({ kind: 'schedule' as const, id: item.id, title: item.title, at: item.startsAt })),
        ];
        const due = candidates.filter((item) => Date.parse(item.at) <= Date.now()).map((item) => ({
          ...item, key: `dengvis.due.${session.expiresAt}.${item.kind}.${item.id}.${item.at}`,
        })).filter((item) => {
          if (acknowledged.current.has(item.key)) return false;
          try { return !localStorage.getItem(item.key); } catch { return true; }
        }).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
        setQueue(due);
        setIssue('');
      } catch {
        if (!cancelled) {
          setQueue([]);
          setIssue('待办提醒暂时无法同步，正在重连。');
        }
      } finally { fetching = false; }
    };
    void check();
    const timer = window.setInterval(() => void check(), 5_000);
    const resume = () => { if (!document.hidden) void check(); };
    document.addEventListener('visibilitychange', resume);
    return () => { cancelled = true; window.clearInterval(timer); document.removeEventListener('visibilitychange', resume); };
  }, [session]);

  function dismiss() {
    const reminder = queue[0];
    if (!reminder) return;
    acknowledged.current.add(reminder.key);
    try { localStorage.setItem(reminder.key, 'acknowledged'); } catch { /* Keep the in-memory acknowledgement. */ }
    setQueue((before) => before.filter((item) => item.key !== reminder.key));
  }
  return { reminder: queue[0] ?? null, count: queue.length, issue, dismiss };
}
