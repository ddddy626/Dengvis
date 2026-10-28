import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiError, cancelLifeJob, createLifePlan, decideLifePlan, editLifePlan, fetchLifeItems, fetchLifeJobEvents, fetchLifeJobs, fetchLifePlan, fetchMorning, LifeDraftItem, LifeItems, LifeJob, LifeJobEvent, LifePlan, LifeSuggestion, MorningReport, SavedSchedule, SavedTask, suggestLife, updateLifeItem } from './api';

type EditableItem = { kind: 'task' | 'schedule'; title: string; dueAt: string; startsAt: string; endsAt: string };

function localInput(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function editable(item: LifeDraftItem): EditableItem {
  return { kind: item.kind, title: item.title, dueAt: localInput(item.dueAt), startsAt: localInput(item.startsAt), endsAt: localInput(item.endsAt) };
}

function savedTime(value: string | null): string {
  if (!value) return '';
  const utc = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`;
  return new Date(utc).toLocaleString('zh-CN');
}

export function LifePanel({ token }: { token: string | null }) {
  const [intent, setIntent] = useState('帮我安排今天并提醒买牛奶');
  const [useCloudPlan, setUseCloudPlan] = useState(false);
  const [planQuestions, setPlanQuestions] = useState<string[]>([]);
  const [plan, setPlan] = useState<LifePlan | null>(null);
  const [items, setItems] = useState<EditableItem[]>([]);
  const [saved, setSaved] = useState<LifeItems>({ tasks: [], schedules: [] });
  const [morning, setMorning] = useState<MorningReport | null>(null);
  const [jobs, setJobs] = useState<LifeJob[]>([]);
  const [events, setEvents] = useState<{ jobId: number; entries: LifeJobEvent[] } | null>(null);
  const [editing, setEditing] = useState<{ kind: 'task' | 'schedule'; id: number; title: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const request = useRef<{ intent: string; key: string; cloud: boolean; suggestion?: LifeSuggestion } | null>(null);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void fetchLifeItems(token).then((result) => {
      if (active) setSaved(result);
    }).catch(() => {
      if (active) setMessage('暂时无法读取生活事项。');
    });
    void fetchLifeJobs(token).then((result) => { if (active) setJobs(result); }).catch(() => {});
    return () => { active = false; };
  }, [token]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || busy || !intent.trim()) return;
    setBusy(true); setMessage('');
    try {
      if (!request.current || request.current.intent !== intent.trim() || request.current.cloud !== useCloudPlan) {
        request.current = { intent: intent.trim(), key: crypto.randomUUID().replaceAll('-', ''), cloud: useCloudPlan };
      }
      if (useCloudPlan && !request.current.suggestion) request.current.suggestion = await suggestLife(token, intent.trim());
      const result = await createLifePlan(token, intent.trim(), request.current.key, request.current.suggestion?.items);
      setPlan(result);
      setPlanQuestions(request.current.suggestion?.questions ?? []);
      setJobs(await fetchLifeJobs(token));
      setItems(result.items.map(editable));
      setMessage('草案尚未写入。请编辑后查看并决定是否授权。');
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.message : '草案生成失败，请重试。');
    } finally {
      setBusy(false);
    }
  }

  function change(index: number, patch: Partial<EditableItem>) {
    setItems((current) => current.map((item, position) => position === index ? { ...item, ...patch } : item));
  }

  async function decide(decision: 'allow_once' | 'deny') {
    if (!token || !plan || busy) return;
    setBusy(true); setMessage('');
    try {
      if (decision === 'allow_once') {
        const draft: LifeDraftItem[] = items.map((item) => {
          if (!item.title.trim()) throw new Error('每个事项都需要标题。');
          if (item.kind === 'schedule') {
            if (!item.startsAt || !item.endsAt) throw new Error('日程需要开始和结束时间。');
            return { kind: 'schedule', title: item.title.trim(), startsAt: new Date(item.startsAt).toISOString(), endsAt: new Date(item.endsAt).toISOString() };
          }
          return { kind: 'task', title: item.title.trim(), ...(item.dueAt ? { dueAt: new Date(item.dueAt).toISOString() } : {}) };
        });
        await editLifePlan(token, plan.jobId, draft);
      }
      const result = await decideLifePlan(token, plan.jobId, decision);
      setPlan(null);
      setPlanQuestions([]);
      request.current = null;
      setMessage(decision === 'deny' ? '已拒绝，未写入任何事项。' : `已保存 ${result.saved.length} 个事项。`);
      setSaved(await fetchLifeItems(token));
      setJobs(await fetchLifeJobs(token));
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : '操作失败，请重试。');
    } finally {
      setBusy(false);
    }
  }

  async function changeSaved(kind: 'task' | 'schedule', item: SavedTask | SavedSchedule, status: string, title = item.title) {
    if (!token || busy) return;
    setBusy(true); setMessage('');
    try {
      const body = kind === 'task'
        ? { title, status, dueAt: (item as SavedTask).dueAt }
        : { title, status, startsAt: (item as SavedSchedule).startsAt, endsAt: (item as SavedSchedule).endsAt };
      await updateLifeItem(token, kind, item.id, body);
      setSaved(await fetchLifeItems(token));
      setMorning(null);
      setEditing(null);
      setMessage('事项已更新。');
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : '修改失败，请重试。');
    } finally { setBusy(false); }
  }

  async function showMorning() {
    if (!token || busy) return;
    setBusy(true); setMessage('');
    try {
      const date = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
      setMorning(await fetchMorning(token, date));
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : '晨报暂时不可用。');
    } finally { setBusy(false); }
  }

  async function cancelJob(jobId: number) {
    if (!token || busy) return;
    setBusy(true); setMessage('');
    try {
      await cancelLifeJob(token, jobId);
      if (plan?.jobId === jobId) { setPlan(null); setPlanQuestions([]); }
      setJobs(await fetchLifeJobs(token));
      setMessage('草案已取消。');
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : '取消失败。'); }
    finally { setBusy(false); }
  }

  async function showEvents(jobId: number) {
    if (!token || busy) return;
    try { setEvents({ jobId, entries: await fetchLifeJobEvents(token, jobId) }); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : '无法读取任务记录。'); }
  }

  async function resumePlan(jobId: number) {
    if (!token || busy || plan) return;
    setBusy(true); setMessage('');
    try {
      const draft = await fetchLifePlan(token, jobId);
      if (draft.status !== 'waiting_approval' || draft.approval.decision !== 'pending') throw new Error('草案已处理，请刷新记录。');
      setPlan(draft);
      setItems(draft.items.map(editable));
      setIntent(draft.intent);
      setPlanQuestions([]);
      request.current = null;
      setMessage('已恢复待批准草案，请检查后决定。');
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : '无法恢复草案。'); }
    finally { setBusy(false); }
  }

  return <section className="life-panel" aria-label="生活任务">
    <div className="life-heading"><h2>生活任务</h2><span>游客演示 · 请使用虚构内容</span></div>
    <form onSubmit={(event) => void create(event)}>
      <label htmlFor="life-intent">想安排什么？</label>
      <textarea id="life-intent" value={intent} onChange={(event) => setIntent(event.target.value)} rows={2} maxLength={500} disabled={!token || busy || !!plan} />
      <label className="cloud-planner-optin"><input type="checkbox" checked={useCloudPlan} onChange={(event) => setUseCloudPlan(event.target.checked)} disabled={!token || busy || !!plan} /> 使用云端智能拆解（本次意图会发送给 DeepSeek；草案仍需确认）</label>
      <button type="submit" disabled={!token || busy || !!plan || !intent.trim()}>生成草案</button>
    </form>
    {plan && <div className="life-draft">
      <h3>待批准的写入清单</h3>
      <p>仅在你点击“批准并保存”后写入本次游客会话。</p>
      {planQuestions.length > 0 && <p>需要你补充：{planQuestions.join('；')}</p>}
      {items.map((item, index) => <div className="life-item-edit" key={index}>
        <select aria-label={`事项 ${index + 1} 类型`} value={item.kind} onChange={(event) => change(index, { kind: event.target.value as 'task' | 'schedule' })}>
          <option value="task">待办</option><option value="schedule">日程</option>
        </select>
        <input aria-label={`事项 ${index + 1} 标题`} value={item.title} maxLength={255} onChange={(event) => change(index, { title: event.target.value })} />
        {item.kind === 'task' && <label>截止时间（可选）<input type="datetime-local" value={item.dueAt} onChange={(event) => change(index, { dueAt: event.target.value })} /></label>}
        {item.kind === 'schedule' && <><label>开始<input type="datetime-local" value={item.startsAt} onChange={(event) => change(index, { startsAt: event.target.value })} /></label><label>结束<input type="datetime-local" value={item.endsAt} onChange={(event) => change(index, { endsAt: event.target.value })} /></label></>}
        <button type="button" onClick={() => setItems((current) => current.filter((_, position) => position !== index))} disabled={items.length <= 1 || busy}>移除</button>
      </div>)}
      <button type="button" onClick={() => setItems((current) => [...current, { kind: 'task', title: '', dueAt: '', startsAt: '', endsAt: '' }])} disabled={items.length >= 8 || busy}>添加事项</button>
      <div className="life-actions"><button type="button" onClick={() => void decide('allow_once')} disabled={busy}>批准并保存</button><button type="button" onClick={() => void decide('deny')} disabled={busy}>拒绝</button></div>
    </div>}
    {message && <p className="life-message" role="status">{message}</p>}
    <div className="life-saved"><h3>已保存的事项</h3>
      {!saved.tasks.length && !saved.schedules.length && <p>暂无事项。</p>}
      <ul>{saved.tasks.map((item) => <li key={`task-${item.id}`}>待办 · {item.title} · {item.status}{item.dueAt ? ` · ${savedTime(item.dueAt)}` : ''} <button type="button" onClick={() => setEditing({ kind: 'task', id: item.id, title: item.title })}>编辑</button> <button type="button" disabled={busy || item.status === 'done'} onClick={() => void changeSaved('task', item, 'done')}>完成</button> <button type="button" disabled={busy || item.status === 'cancelled'} onClick={() => void changeSaved('task', item, 'cancelled')}>取消</button></li>)}{saved.schedules.map((item) => <li key={`schedule-${item.id}`}>日程 · {item.title} · {savedTime(item.startsAt)} · {item.status} <button type="button" onClick={() => setEditing({ kind: 'schedule', id: item.id, title: item.title })}>编辑</button> <button type="button" disabled={busy || item.status === 'cancelled'} onClick={() => void changeSaved('schedule', item, 'cancelled')}>取消</button></li>)}</ul>
      {editing && <div className="life-inline-edit"><input aria-label="修改事项标题" maxLength={255} value={editing.title} onChange={(event) => setEditing({ ...editing, title: event.target.value })} /><button type="button" disabled={busy || !editing.title.trim()} onClick={() => { const item = editing.kind === 'task' ? saved.tasks.find((value) => value.id === editing.id) : saved.schedules.find((value) => value.id === editing.id); if (item) void changeSaved(editing.kind, item, item.status, editing.title.trim()); }}>保存修改</button><button type="button" onClick={() => setEditing(null)}>放弃</button></div>}
    </div>
    <div className="life-saved"><h3>晨报</h3><button type="button" disabled={!token || busy} onClick={() => void showMorning()}>查看今日晨报</button>
      {morning && <p>日期：{morning.date}；待办 {morning.tasks.filter((item) => item.status === 'open').length} 项，日程 {morning.schedules.filter((item) => item.status === 'planned').length} 项。睡眠数据：{morning.sleep.status === 'not_authorized' ? '未授权' : morning.sleep.status === 'not_synced' ? '未同步' : morning.sleep.status === 'failed' ? '获取失败' : morning.sleep.minutes == null ? '无数据' : `${morning.sleep.minutes} 分钟`}。来源：内部事项记录。</p>}
    </div>
    <div className="life-saved"><h3>任务记录</h3><button type="button" disabled={!token || busy} onClick={() => { if (token) void fetchLifeJobs(token).then(setJobs).catch(() => setMessage('无法刷新任务记录。')); }}>刷新</button>
      {!jobs.length && <p>暂无任务记录。</p>}
      <ul>{jobs.map((job) => <li key={job.jobId}>#{job.jobId} · {job.status} · {job.preview} · {job.latestEvent ?? '等待处理'} <button type="button" onClick={() => void showEvents(job.jobId)}>查看过程</button> {job.status === 'waiting_approval' && <><button type="button" disabled={busy || !!plan} onClick={() => void resumePlan(job.jobId)}>恢复草案</button> <button type="button" disabled={busy} onClick={() => void cancelJob(job.jobId)}>取消草案</button></>}</li>)}</ul>
      {events && <p>任务 #{events.jobId}：{events.entries.map((event) => `${event.seq}. ${event.summary}`).join('；')}</p>}
    </div>
  </section>;
}
