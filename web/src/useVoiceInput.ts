import { useEffect, useRef, useState } from 'react';

type VoiceResult = { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> };
type Recognizer = {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: VoiceResult) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void; stop: () => void; abort: () => void;
};
type VoiceWindow = Window & { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer };

export function useVoiceInput(onSubmit: (text: string) => void, onNotice: (message: string) => void) {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const active = useRef<Recognizer | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const callbacks = useRef({ onSubmit, onNotice });
  callbacks.current = { onSubmit, onNotice };

  useEffect(() => () => {
    window.clearTimeout(timer.current);
    if (active.current) {
      active.current.onend = null;
      active.current.onerror = null;
      active.current.onresult = null;
      active.current.abort();
    }
  }, []);

  function capture() {
    if (active.current) { active.current.stop(); return; }
    const source = window as VoiceWindow;
    const Recognition = source.SpeechRecognition ?? source.webkitSpeechRecognition;
    if (!Recognition) {
      callbacks.current.onNotice('此浏览器不支持语音识别。请点击右侧按钮，使用文字输入。');
      return;
    }
    const recognizer = new Recognition();
    recognizer.lang = 'zh-CN';
    recognizer.continuous = false;
    recognizer.interimResults = true;
    let finalText = '';
    let failed = false;
    recognizer.onresult = (event) => {
      const results = Array.from(event.results);
      finalText = results.filter((item) => item.isFinal).map((item) => item[0]?.transcript ?? '').join('').trim();
      setTranscript(results.map((item) => item[0]?.transcript ?? '').join(''));
    };
    recognizer.onerror = (event) => {
      failed = true;
      const messages: Record<string, string> = {
        'not-allowed': '麦克风权限未开启。请在浏览器中允许麦克风，或从右侧输入文字。',
        'service-not-allowed': '浏览器禁用了语音识别服务，请从右侧输入文字。',
        'audio-capture': '没有找到可用的麦克风，请检查设备。',
        'network': '语音识别服务连接失败，请重试或从右侧输入文字。',
        'no-speech': '没有听清，请点击核心再说一次。',
      };
      callbacks.current.onNotice(messages[event.error] ?? '语音识别失败，请重试或从右侧输入文字。');
    };
    recognizer.onend = () => {
      if (active.current !== recognizer) return;
      active.current = null;
      window.clearTimeout(timer.current);
      setListening(false);
      if (!failed && finalText) callbacks.current.onSubmit(finalText);
      else if (!failed) callbacks.current.onNotice('没有听清，请点击核心再说一次。');
    };
    try {
      active.current = recognizer;
      setTranscript('');
      recognizer.start();
      setListening(true);
      timer.current = window.setTimeout(() => {
        if (active.current === recognizer) recognizer.stop();
      }, 30_000);
    } catch {
      active.current = null;
      setListening(false);
      callbacks.current.onNotice('语音无法启动，请检查麦克风权限，或从右侧输入文字。');
    }
  }
  return { listening, transcript, capture };
}
