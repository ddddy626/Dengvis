import { useEffect, useState } from 'react';
import { ApiError, createLifePlan, decideLifePlan, fetchLifeItems, fetchLifePlan, fetchMorning, GuestSession, LifeItems, LifePlan, MorningReport, updateLifeItem } from './api';

type Progress = { phase: number; runId: string; dayPlanId: number | null; studyPlanId: number | null };

function freshProgress(): Progress {
  return { phase: 0, runId: crypto.randomUUID().replaceAll('-', ''), dayPlanId: null, studyPlanId: null };
}

function todayInBeijing(): string {
  return new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function savedProgress(key: string): Progress {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? 'null') as Partial<Progress> | null;
    if (value && Number.isInteger(value.phase) && (value.phase ?? -1) >= 0 && (value.phase ?? 5) <= 4 &&
        typeof value.runId === 'string' && /^[a-f0-9]{32}$/.test(value.runId)) {
      return { phase: value.phase!, runId: value.runId,
        dayPlanId: typeof value.dayPlanId === 'number' ? value.dayPlanId : null,
        studyPlanId: typeof value.studyPlanId === 'number' ? value.studyPlanId : null };
    }
  } catch { /* A damaged local guide starts from morning. */ }
  return freshProgress();
}

function sleepLabel(status: string): string {
  return { not_authorized: '未授权', not_synced: '未同步', failed: '获取失败', available: '可用' }[status] ?? '未知';
}

export function DayDemoPanel({ session }: { session: GuestSession }) {
  const storageKey = `jarvis.day.${session.expiresAt}`;
  const [progress, setProgress] = useState<Progress>(() => savedProgress(storageKey));
  const [dayPlan, setDayPlan] = useState<LifePlan | null>(null);
  const [studyPlan, setStudyPlan] = useState<LifePlan | null>(null);
  const [morning, setMorning] = useState<MorningReport | null>(null);
  const [saved, setSaved] = useState<LifeItems>({ tasks: [], schedules: [] });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [confirmReset, setConfirmReset] = useState(false);
  const date = todayInBeijing();

  function advance(patch: Partial<Progress>) {
    setProgress((current) => {
      const next = { ...current, ...patch };
      sessionStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  }

  useEffect(() => {
    let active = true;
    const restored = savedProgress(storageKey);
    setProgress(restored);
    setDayPlan(null); setStudyPlan(null); setLoading(true); setMessage('');
    void Promise.all([
      fetchMorning(session.token, todayInBeijing()),
      fetchLifeItems(session.token),
      restored.dayPlanId ? fetchLifePlan(session.token, restored.dayPlanId) : Promise.resolve(null),
      restored.studyPlanId ? fetchLifePlan(session.token, restored.studyPlanId) : Promise.resolve(null),
    ]).then(([report, items, first, second]) => {
      if (!active) return;
      setMorning(report); setSaved(items); setDayPlan(first); setStudyPlan(second);
    }).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : '暂时无法读取演示进度，请刷新。');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [session.token, storageKey]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setMessage('');
    try { await action(); }
    catch (error) { setMessage(error instanceof ApiError || error instanceof Error ? error.message : '操作失败，请重试。'); }
    finally { setBusy(false); }
  }

  async function refresh() {
    const [report, items, first, second] = await Promise.all([
      fetchMorning(session.token, date), fetchLifeItems(session.token),
      progress.dayPlanId ? fetchLifePlan(session.token, progress.dayPlanId) : Promise.resolve(null),
      progress.studyPlanId ? fetchLifePlan(session.token, progress.studyPlanId) : Promise.resolve(null),
    ]);
    setMorning(report); setSaved(items); setDayPlan(first); setStudyPlan(second);
  }

  const references = [...(dayPlan?.saved ?? []), ...(studyPlan?.saved ?? [])];
  const owned = [
    ...saved.tasks.filter((item) => references.some((ref) => ref.kind === 'task' && ref.id === item.id)).map((item) => ({ kind: 'task' as const, item })),
    ...saved.schedules.filter((item) => references.some((ref) => ref.kind === 'schedule' && ref.id === item.id)).map((item) => ({ kind: 'schedule' as const, item })),
  ];
  const finished = owned.filter(({ item }) => item.status === 'done' || item.status === 'completed').length;

  return <section className="day-demo" aria-label="固定的一天演示">
    <div className="day-demo-top">
      <div><h2>大学生小林的一天</h2><p>固定演示 · {date} · 第 {progress.phase + 1}/5 段</p></div>
      <button type="button" className="day-secondary" disabled={busy || loading} onClick={() => void run(async () => { await refresh(); setMessage('已读取当前游客会话状态。'); })}>刷新状态</button>
    </div>
    <p className="day-note">剧情和资料摘录是演示样例；晨报与批准后的任务来自当前游客会话。全程不调用收费模型。</p>
    {message && <p className="day-message" role="status">{message}</p>}
    {loading && <p role="status">正在读取演示进度…</p>}

    {!loading && progress.phase === 0 && <div className="day-stage">
      <h3>07:30 · 早晨</h3>
      <p>演示对话：早上好。先吃早餐、带上水杯，再看看今天有哪些生活小事要安排。</p>
      <p>当前游客晨报：待办 {morning?.tasks.filter((item) => item.status === 'open').length ?? '—'} 项，日程 {morning?.schedules.filter((item) => item.status === 'planned').length ?? '—'} 项。</p>
      <p>睡眠数据：{sleepLabel(morning?.sleep.status ?? 'unknown')}。不使用虚构健康数值。</p>
      <button type="button" onClick={() => advance({ phase: 1 })}>进入上午安排</button>
    </div>}

    {!loading && progress.phase === 1 && <div className="day-stage">
      <h3>09:00 · 安排今天</h3>
      <p>固定建议：下课后买牛奶和水果；给家人回消息；19:00 洗衣服。生成草案不会写入事项。</p>
      {!dayPlan && <button type="button" disabled={busy} onClick={() => void run(async () => {
        const plan = await createLifePlan(session.token, '固定演示：安排大学生小林的一天', `daydemo-${progress.runId}-day`, [
          { kind: 'task', title: '下课后买牛奶和水果' },
          { kind: 'task', title: '给家人回消息' },
          { kind: 'schedule', title: '19:00 洗衣服', startsAt: new Date(`${date}T19:00:00+08:00`).toISOString(), endsAt: new Date(`${date}T20:00:00+08:00`).toISOString() },
        ]);
        setDayPlan(plan); advance({ dayPlanId: plan.jobId }); setMessage('草案已生成，尚未写入。');
      })}>生成固定草案</button>}
      {dayPlan && <div className="day-draft">
        <p>草案 #{dayPlan.jobId} · {dayPlan.status}</p>
        <ul>{dayPlan.items.map((item, index) => <li key={index}>{item.title}</li>)}</ul>
        {dayPlan.status === 'waiting_approval' ? <>
          <p>批准后，这 3 项会真实保存到当前游客会话。</p>
          <div className="day-actions">
            <button type="button" disabled={busy} onClick={() => void run(async () => {
              const result = await decideLifePlan(session.token, dayPlan.jobId, 'allow_once');
              setDayPlan(result);
              if (result.status === 'succeeded') { setSaved(await fetchLifeItems(session.token)); advance({ phase: 2 }); }
              else setMessage(`草案未保存（${result.status}），请重新生成。`);
            })}>批准并保存</button>
            <button type="button" className="day-secondary" disabled={busy} onClick={() => void run(async () => {
              await decideLifePlan(session.token, dayPlan.jobId, 'deny');
              setDayPlan(null); advance({ dayPlanId: null, runId: freshProgress().runId });
              setMessage('已拒绝，未写入任何事项。可重新生成草案。');
            })}>拒绝</button>
          </div>
        </> : dayPlan.status === 'succeeded' ? <button type="button" onClick={() => advance({ phase: 2 })}>进入下午整理</button>
          : <button type="button" onClick={() => { setDayPlan(null); advance({ dayPlanId: null, runId: freshProgress().runId }); }}>重新生成草案</button>}
      </div>}
    </div>}

    {!loading && progress.phase === 2 && <div className="day-stage">
      <h3>15:30 · 整理明天</h3>
      <p>内置演示样例《校园生活清单》第 1 页：晚上看一眼明天的课程，提前放好课本、水杯和充电器。此段没有读取你的 PC 文件。</p>
      {!studyPlan && <button type="button" disabled={busy} onClick={() => void run(async () => {
        const plan = await createLifePlan(session.token, '固定演示：根据内置校园生活样例整理明天', `daydemo-${progress.runId}-study`, [
          { kind: 'task', title: '睡前整理明天要带的课本和充电器' },
        ]);
        setStudyPlan(plan); advance({ studyPlanId: plan.jobId }); setMessage('资料待办草案已生成，尚未写入。');
      })}>生成资料待办草案</button>}
      {studyPlan && <div className="day-draft">
        <p>草案 #{studyPlan.jobId} · {studyPlan.status}：{studyPlan.items.map((item) => item.title).join('；')}</p>
        {studyPlan.status === 'waiting_approval' ? <div className="day-actions">
          <button type="button" disabled={busy} onClick={() => void run(async () => {
            const result = await decideLifePlan(session.token, studyPlan.jobId, 'allow_once');
            setStudyPlan(result);
            if (result.status === 'succeeded') { setSaved(await fetchLifeItems(session.token)); advance({ phase: 3 }); }
            else setMessage(`草案未保存（${result.status}）。`);
          })}>批准并保存</button>
          <button type="button" className="day-secondary" disabled={busy} onClick={() => void run(async () => {
            const result = await decideLifePlan(session.token, studyPlan.jobId, 'deny');
            setStudyPlan(result); advance({ phase: 3 });
          })}>拒绝并继续</button>
        </div> : <button type="button" onClick={() => advance({ phase: 3 })}>进入傍晚执行</button>}
      </div>}
      {!studyPlan && <button type="button" className="day-secondary" onClick={() => advance({ phase: 3 })}>跳过资料待办</button>}
    </div>}

    {!loading && progress.phase === 3 && <div className="day-stage">
      <h3>19:00 · 完成事项</h3>
      <p>以下是本次演示中你实际批准保存的事项。逐项完成后进入晚间回顾。</p>
      {owned.length === 0 && <p>暂未读到本次事项，请刷新状态。</p>}
      <ul className="day-saved">{owned.map(({ kind, item }) => <li key={`${kind}-${item.id}`}>
        <span>{item.title} · {item.status === 'done' || item.status === 'completed' ? '已完成' : '进行中'}</span>
        {(item.status === 'open' || item.status === 'planned') && <button type="button" disabled={busy} onClick={() => void run(async () => {
          await updateLifeItem(session.token, kind, item.id, kind === 'task'
            ? { title: item.title, status: 'done', dueAt: saved.tasks.find((entry) => entry.id === item.id)?.dueAt }
            : { title: item.title, status: 'completed', startsAt: saved.schedules.find((entry) => entry.id === item.id)?.startsAt, endsAt: saved.schedules.find((entry) => entry.id === item.id)?.endsAt });
          setSaved(await fetchLifeItems(session.token));
        })}>标记完成</button>}
      </li>)}</ul>
      <button type="button" disabled={owned.length === 0} onClick={() => advance({ phase: 4 })}>进入晚间回顾</button>
    </div>}

    {!loading && progress.phase === 4 && <div className="day-stage">
      <h3>21:30 · 晚间回顾</h3>
      <p>演示对话：今天推进了 {finished} / {owned.length} 项；未完成的仍留在任务列表，明天可继续处理。</p>
      <ul>{owned.map(({ kind, item }) => <li key={`${kind}-${item.id}`}>{item.title}：{item.status === 'done' || item.status === 'completed' ? '已完成' : '未完成'}</li>)}</ul>
      <p>回顾只汇总本次批准的真实事项；没有生成虚构的睡眠或 PC 数据。</p>
      <button type="button" onClick={() => setConfirmReset(true)}>重新体验一天</button>
      {confirmReset && <div className="day-reset">
        <p>重新开始只重置演示引导；已经保存的任务不会删除。再次批准会新增事项。</p>
        <div className="day-actions">
          <button type="button" onClick={() => { setDayPlan(null); setStudyPlan(null); setConfirmReset(false); advance(freshProgress()); }}>确认重置引导</button>
          <button type="button" className="day-secondary" onClick={() => setConfirmReset(false)}>取消</button>
        </div>
      </div>}
    </div>}
  </section>;
}
