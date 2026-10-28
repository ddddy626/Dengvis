import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiError, fetchHistory, GuestSession, initializeGuestSession, renewGuestSession, sendChat } from './api';
import { CoreViewer } from './CoreViewer';
import { LifePanel } from './LifePanel';
import { useVoiceInput } from './useVoiceInput';
import { useTaskReminders } from './useTaskReminders';
import { requestsTask, resolveTask, TaskAttempt } from './assistantTasks';

type Entry = { role: 'user' | 'assistant'; text: string };
type ViewError = { message: string; retryable: boolean };
type HudMode = 'idle' | 'thinking' | 'speaking' | 'error';
const HUD_LABELS: Record<HudMode, string> = { idle: '待机', thinking: '处理中', speaking: '正在朗读', error: '需要处理' };

export function App() {
  const [draft, setDraft] = useState('');
  const [entries, setEntries] = useState<Entry[]>([]);
  const [session, setSession] = useState<GuestSession | null>(null);
  const [connecting, setConnecting] = useState(true);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ViewError | null>(null);
  const [lastMessage, setLastMessage] = useState('');
  const [speaking, setSpeaking] = useState(false);
  const [surface, setSurface] = useState<'closed' | 'chat' | 'tasks'>('closed');
  const [reply, setReply] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const drawerToggle = useRef<HTMLButtonElement>(null);
  const sending = useRef(false);
  const taskAttempt = useRef<TaskAttempt | null>(null);
  const [taskContext, setTaskContext] = useState('');
  const { listening, transcript, capture } = useVoiceInput((text) => void send(text), setNotice);
  const { reminder, count: reminderCount, issue: reminderIssue, dismiss: dismissReminder } = useTaskReminders(session);

  useEffect(() => () => window.speechSynthesis?.cancel(), []);
  useEffect(() => {
    if (reply !== null && !dialog.current?.open) dialog.current?.showModal();
    if (reply === null && dialog.current?.open) dialog.current.close();
  }, [reply]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && surface !== 'closed' && !dialog.current?.open) {
        setSurface('closed');
        drawerToggle.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [surface]);

  function captureVoice() {
    if (!session || connecting) { setNotice('正在连接助手，请稍后再试。'); return; }
    if (sending.current) { setNotice('正在处理上一条消息，请稍等。'); return; }
    window.speechSynthesis?.cancel();
    setSpeaking(false);
    setNotice('');
    setReply(null);
    capture();
  }

  function speakReply(content: string) {
    if (!('speechSynthesis' in window)) { setNotice('浏览器不支持朗读，文字回复仍可阅读。'); return; }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(content);
    utterance.lang = 'zh-CN';
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => { setSpeaking(false); setNotice('朗读失败，文字回复仍可阅读。'); };
    window.speechSynthesis.speak(utterance);
  }

  const hudMode: HudMode = error ? 'error' : busy ? 'thinking' : speaking ? 'speaking' : 'idle';

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { session: current, renewed } = await initializeGuestSession();
        const history = await fetchHistory(current.token);
        if (cancelled) return;
        setSession(current);
        setEntries(history.messages.map((item) => ({ role: item.role, text: item.content })));
        if (renewed) setNotice('上一次游客会话已结束，已开启新会话。');
      } catch (cause) {
        if (!cancelled) {
          setError({ message: cause instanceof ApiError ? cause.message : '无法连接本地服务。请检查后端是否已启动。', retryable: true });
          setNotice('助手连接失败，请刷新页面重试。');
        }
      } finally {
        if (!cancelled) setConnecting(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function send(message: string) {
    if (!message.trim() || sending.current || !session) return;
    if (message.length > 4000) { setNotice('内容过长，请缩短后再发送。'); return; }
    if (taskContext && /^(取消|算了|不用了|不需要了|取消这条待办)[。！!]?$/u.test(message.trim())) {
      setTaskContext('');
      taskAttempt.current = null;
      setDraft('');
      setError(null);
      setReply('已取消这条未保存的待办。');
      return;
    }
    sending.current = true;
    setBusy(true);
    setError(null);
    setLastMessage(message);
    try {
      if (taskContext || requestsTask(message) || taskAttempt.current?.message === message) {
        const attempt = taskAttempt.current?.message === message ? taskAttempt.current : {
          message, intent: taskContext ? `${taskContext}\n补充：${message}` : message,
          key: `voice_${crypto.randomUUID()}`,
        };
        taskAttempt.current = attempt;
        const result = await resolveTask(session.token, attempt);
        setTaskContext(result.needsTime ? attempt.intent : '');
        taskAttempt.current = null;
        setEntries((before) => [...before, { role: 'user', text: message }, { role: 'assistant', text: result.reply }]);
        setDraft('');
        setReply(result.reply);
        setNotice('');
        return;
      }
      const result = await sendChat(session.token, message);
      setEntries((before) => [...before, { role: 'user', text: message }, { role: 'assistant', text: result.reply }]);
      setDraft('');
      setReply(result.reply);
      setNotice('');
    } catch (cause) {
      if (cause instanceof ApiError && (cause.code === 'DEMO_SESSION_EXPIRED' || cause.code === 'DEMO_SESSION_INVALID')) {
        try {
          const fresh = await renewGuestSession();
          setSession(fresh);
          setEntries([]);
          setTaskContext('');
          taskAttempt.current = null;
          setNotice('游客会话已结束，已开启新会话。');
          setError({ message: '请重新发送这条消息。', retryable: true });
        } catch {
          setSession(null);
          setError({ message: '无法开启新的游客会话，请刷新页面重试。', retryable: false });
        }
      } else {
        setError({ message: cause instanceof ApiError ? cause.message : '无法连接本地服务。请检查后端是否已启动。', retryable: cause instanceof ApiError ? cause.retryable : true });
      }
      setReply('这次请求没有完成。请查看下方原因后重试。');
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(draft.trim());
  }

  return <main className="orb-shell">
    <header className="orb-topbar"><strong>Dengvis</strong><span aria-live="polite">{listening ? '正在聆听' : HUD_LABELS[hudMode]}</span></header>
    <section className="orb-stage" aria-label="Dengvis 助手">
      <CoreViewer mode={hudMode} onActivate={captureVoice} />
      <button className="drawer-toggle" ref={drawerToggle} type="button" aria-label={surface === 'closed' ? '展开助手侧栏' : '收起助手侧栏'} aria-expanded={surface !== 'closed'} aria-controls="assistant-drawer" onClick={() => setSurface((current) => current === 'closed' ? 'chat' : 'closed')}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d={surface === 'closed' ? 'M15 5L8 12L15 19' : 'M9 5L16 12L9 19'} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg><span>助手</span>
      </button>
      <div className="voice-status" role="status" aria-live="polite">
        {listening ? <><strong>正在聆听</strong><p>{transcript || '请说话，结束后会自动发送。'}</p><button type="button" onClick={captureVoice}>结束并发送</button></> : busy ? <p>正在处理你的消息…</p> : notice ? <p>{notice}</p> : <p>点击核心说话 · 按住核心加速</p>}
        {reminderIssue && <p className="reminder-issue">{reminderIssue}</p>}
      </div>
      {reminder && reply === null && <aside className="reminder-toast" role="alert">
        <span>{new Date(reminder.at).toLocaleString('zh-CN')} · {reminder.kind === 'task' ? '待办提醒' : '日程提醒'}{reminderCount > 1 ? `（还有 ${reminderCount - 1} 条）` : ''}</span>
        <p>{reminder.title}</p>
        <div><button type="button" onClick={() => { setSurface('tasks'); dismissReminder(); }}>查看待办</button><button type="button" onClick={dismissReminder}>知道了</button></div>
      </aside>}
      {surface !== 'closed' && <section id="assistant-drawer" className="assistant-sheet" aria-label="助手操作区">
        <div className="assistant-heading"><div><h1>{surface === 'chat' ? '和 Dengvis 对话' : '生活任务'}</h1><span>{connecting ? '正在连接…' : session ? '游客会话' : '连接失败'}</span></div><button type="button" onClick={() => { setSurface('closed'); drawerToggle.current?.focus(); }} aria-label="收起助手">关闭</button></div>
        <div className="assistant-tabs"><button type="button" aria-pressed={surface === 'chat'} onClick={() => setSurface('chat')}>对话</button><button type="button" aria-pressed={surface === 'tasks'} onClick={() => setSurface('tasks')}>任务</button></div>
        {surface === 'tasks' ? <div className="assistant-task-scroll"><LifePanel token={session?.token ?? null} /></div> : <>
          <div className="messages" aria-live="polite">
            {notice && <div className="context-note" role="status">{notice}</div>}
            {entries.length === 0 && <div className="empty"><p>有什么需要我帮你处理？</p><span>点击核心直接说话，也可以在这里输入文字。</span></div>}
            {entries.map((entry, index) => <div className={`message ${entry.role}`} key={`${index}-${entry.role}`}><span className="speaker">{entry.role === 'user' ? '你' : 'Dengvis'}</span><p>{entry.text}</p>{entry.role === 'assistant' && <button className="read-reply" type="button" onClick={() => speakReply(entry.text)}>朗读回复</button>}</div>)}
            {busy && <div className="message assistant waiting"><span className="speaker">Dengvis</span><p>正在等待回复…</p></div>}
          </div>
          {error && <div className="error" role="alert"><strong>暂时无法继续</strong><span>{error.message}</span>{error.retryable && lastMessage && session && <button type="button" onClick={() => void send(lastMessage)} disabled={busy}>重试</button>}</div>}
          <form className="composer" onSubmit={submit}>
            <label htmlFor="message">消息</label>
            <div className="composer-row"><textarea id="message" value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4000} rows={2} placeholder="输入想让 Dengvis 回答的问题" disabled={busy || !session || listening} /><button type="button" onClick={captureVoice} disabled={busy || !session}>{listening ? '停止' : '语音'}</button><button type="submit" disabled={busy || !session || listening || !draft.trim()}>发送</button></div>
            <span className="composer-hint">明确说“提醒我”可自动保存待办；时间不清楚会先询问。页面开启时提供到时提醒。</span>
            {taskContext && <button type="button" disabled={busy} onClick={() => { setTaskContext(''); taskAttempt.current = null; setNotice('已取消这条未保存的待办。'); }}>取消这条待办</button>}
          </form>
        </>}
      </section>}
      <dialog ref={dialog} className="reply-dialog" aria-labelledby="reply-title" onCancel={() => setReply(null)} onClose={() => setReply(null)}>
        <div className="reply-heading"><h2 id="reply-title">{error ? '需要处理' : 'Dengvis'}</h2><button type="button" onClick={() => setReply(null)} aria-label="关闭回答窗口">关闭</button></div>
        {reminder && <aside className="reply-reminder" role="alert"><strong>到时间了：{reminder.title}</strong><p>{new Date(reminder.at).toLocaleString('zh-CN')}</p><button type="button" onClick={dismissReminder}>知道了</button></aside>}
        <div className="reply-content"><p>{reply}</p>{error && <p role="alert">{error.message}</p>}</div>
        <div className="reply-actions">
          {error ? error.retryable && lastMessage && session && <button type="button" disabled={busy} onClick={() => { setReply(null); void send(lastMessage); }}>重试</button> : <button type="button" onClick={() => reply && speakReply(reply)}>朗读回答</button>}
          <button type="button" onClick={captureVoice} disabled={busy || !session}>继续说</button>
          {taskContext && <button type="button" onClick={() => { setTaskContext(''); taskAttempt.current = null; setReply(null); }}>取消这条待办</button>}
        </div>
      </dialog>
    </section>
  </main>;
}
