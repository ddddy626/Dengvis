import { ApiError, createLifePlan, decideLifePlan, LifeDraftItem, suggestLife } from './api';

export type TaskAttempt = { message: string; intent: string; key: string; items?: LifeDraftItem[] };

export function requestsTask(message: string): boolean {
  // Require a direct request, not quoted examples, questions about reminders, or a negation.
  const text = message.trim().replace(/^(?:Dengvis|邓维斯|你好)[，,\s]*/i, '');
  if (/[“”「」"?？]|不要|不用|不需要|别提醒|取消|假如|假设|如果|例如|怎么|如何/.test(text)) return false;
  return /^(?:请|麻烦)?\s*(?:提醒我|帮我.*(?:提醒|记.*(?:待办|事项)|添加.*(?:待办|事项))|记(?:下|个|一条).*待办|添加.*待办|(?:今天|明天|后天|今晚|上午|下午|晚上|早上|周|星期|下周|\d).{0,40}提醒我)/.test(text);
}

export async function resolveTask(token: string, attempt: TaskAttempt): Promise<{ reply: string; needsTime: boolean }> {
  if (attempt.intent.length > 500) throw new ApiError('TASK_TOO_LONG', '这条待办描述太长，请缩短至 500 字以内后重新说。', false);
  if (!attempt.items) {
    const suggestion = await suggestLife(token, attempt.intent);
    const questions = [...suggestion.questions];
    if (suggestion.items.some((item) => !(item.kind === 'task' ? item.dueAt : item.startsAt))) {
      questions.push('希望在什么日期、几点提醒你？例如：明天下午 3 点。');
    }
    if (suggestion.items.some((item) => {
      const at = item.kind === 'task' ? item.dueAt : item.startsAt;
      return at && (!Number.isFinite(Date.parse(at)) || Date.parse(at) <= Date.now());
    })) questions.push('这个时间已过去或无法识别，请告诉我新的提醒时间。');
    if (questions.length) return { reply: `还没有保存待办。\n${[...new Set(questions)].join('\n')}`, needsTime: true };
    attempt.items = suggestion.items;
  }
  // Reuse the same key and exact items after network failure, including a lost save response.
  const plan = await createLifePlan(token, attempt.intent, attempt.key, attempt.items);
  const saved = await decideLifePlan(token, plan.jobId, 'allow_once');
  if (saved.status !== 'succeeded' || saved.saved.length !== attempt.items.length) {
    throw new ApiError('TASK_NOT_SAVED', '待办没有保存成功，请在右侧任务列表检查后重新创建。', false);
  }
  const format = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  const lines = saved.items.map((item) => `${item.title} · ${format.format(new Date((item.kind === 'task' ? item.dueAt : item.startsAt)!))}`);
  return { reply: `已保存。\n${lines.join('\n')}\n（北京时间；页面开启且游客会话有效时，会弹窗提醒。）`, needsTime: false };
}
