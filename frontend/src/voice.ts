// Browser speech, both ways: speech-to-text (Chrome, Edge and Safari; Chrome sends the audio to Google's speech
// service, Safari to Apple's) and text-to-speech (every current browser). Nothing here talks to the MarsWalk server.

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canListen = (): boolean => recognitionCtor() !== null;
export const canSpeak = (): boolean => typeof window !== 'undefined' && 'speechSynthesis' in window;

const ERRORS: Record<string, string> = {
  'not-allowed': 'The microphone is blocked for this page. Allow it in the browser’s site settings, or type the question.',
  'service-not-allowed': 'The microphone is blocked for this page. Allow it in the browser’s site settings, or type the question.',
  'no-speech': 'Nothing was heard. Press the microphone and ask again.',
  'audio-capture': 'No microphone was found. Type the question instead.',
  network: 'This browser could not reach its speech service. Chrome and Safari work; you can also type the question.',
};

export interface ListenHandlers {
  /** The words heard so far (updates while speaking). */
  onInterim: (text: string) => void;
  /** The finished question. */
  onFinal: (text: string) => void;
  onError: (message: string) => void;
  /** Listening stopped, for any reason. */
  onEnd: () => void;
}

/** Listen for one question. Returns a function that stops listening early. */
export function listen(h: ListenHandlers): () => void {
  const Ctor = recognitionCtor();
  if (!Ctor) {
    h.onError('This browser has no speech input. Use Chrome or Safari, or type the question.');
    h.onEnd();
    return () => undefined;
  }
  const r = new Ctor();
  r.lang = 'en-US';
  r.interimResults = true;
  r.continuous = false;
  r.maxAlternatives = 1;
  let finalText = '';
  r.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    h.onInterim((finalText + interim).trim());
  };
  r.onerror = (e) => {
    if (e.error !== 'aborted') h.onError(ERRORS[e.error] ?? `Voice input stopped (${e.error}). Type the question instead.`);
  };
  r.onend = () => {
    if (finalText.trim()) h.onFinal(finalText.trim());
    h.onEnd();
  };
  try {
    r.start();
  } catch {
    h.onError('Voice input could not start. Type the question instead.');
    h.onEnd();
  }
  return () => r.stop();
}

/** Read an answer aloud, replacing anything still being read. */
export function speak(text: string): void {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'en-US';
  u.rate = 1.02;
  window.speechSynthesis.speak(u);
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}
