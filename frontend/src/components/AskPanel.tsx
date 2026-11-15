import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { describeError, useAsk } from '../api';
import type { AskAnswer } from '../api';
import { canListen, listen, speak, stopSpeaking } from '../voice';

interface Props {
  live: boolean;
  planId: string | null;
  selectedStopId: string | null;
  elapsedH: number;
  /** What "here" means right now, in a few words. */
  hereHint: string;
  onHighlight: (fc: GeoJSON.FeatureCollection | null) => void;
}

const EXAMPLES = ['How far is S3 from here?', 'How much oxygen does this walk use?', 'How much radiation?', 'When must we turn back?'];

/** Ask the plan a question, by voice or typed. Answers come from the planner's own numbers and are read aloud. */
export function AskPanel({ live, planId, selectedStopId, elapsedH, hereHint, onHighlight }: Props) {
  const ask = useAsk();
  const [text, setText] = useState('');
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [shown, setShown] = useState<AskAnswer | null>(null);
  const stopListening = useRef<(() => void) | null>(null);
  const micAvailable = canListen();

  useEffect(() => () => {
    stopListening.current?.();
    stopSpeaking();
  }, []);

  const submit = (question: string, byVoice: boolean) => {
    const q = question.trim();
    if (!q || !live) return;
    ask.mutate(
      { question: q, plan_id: planId, selected_stop_id: selectedStopId, elapsed_h: elapsedH },
      {
        onSuccess: (r) => {
          setShown(r);
          onHighlight(r.highlight);
          if (byVoice) speak(r.speech);
        },
      },
    );
  };

  const toggleMic = () => {
    stopSpeaking();
    if (listening) {
      stopListening.current?.();
      return;
    }
    setVoiceError(null);
    setText('');
    setListening(true);
    stopListening.current = listen({
      onInterim: setText,
      onFinal: (q) => {
        setText(q);
        submit(q, true);
      },
      onError: setVoiceError,
      onEnd: () => {
        setListening(false);
        stopListening.current = null;
      },
    });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(text, false);
  };
  const close = () => {
    setShown(null);
    stopSpeaking();
    onHighlight(null);
  };

  return (
    <section className="ask" aria-label="Ask about the walk">
      {(shown || ask.isError || voiceError) && (
        <div className="ask-answer" aria-live="polite">
          {shown && (
            <>
              <button type="button" className="ask-close" onClick={close} aria-label="Close the answer">
                ×
              </button>
              <p className="ask-q">{shown.question}</p>
              <p className="ask-a">{shown.answer}</p>
              <div className="ask-tools">
                <button type="button" className="link" onClick={() => speak(shown.speech)}>
                  Read aloud
                </button>
                {shown.here.used && <small>Here: {shown.here.label}</small>}
              </div>
            </>
          )}
          {ask.isError && <p className="ask-error">{describeError(ask.error, 'Answering')}</p>}
          {voiceError && <p className="ask-error">{voiceError}</p>}
        </div>
      )}
      <form className="ask-bar" onSubmit={onSubmit}>
        {micAvailable && (
          <button
            type="button"
            className={`mic${listening ? ' listening' : ''}`}
            onClick={toggleMic}
            disabled={!live}
            aria-pressed={listening}
            aria-label={listening ? 'Stop listening' : 'Ask by voice'}
            title={listening ? 'Stop listening' : 'Ask by voice'}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <rect x="9" y="3" width="6" height="11" rx="3" />
              <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
            </svg>
          </button>
        )}
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={listening ? 'Listening…' : live ? EXAMPLES[0] : 'Start the planner service to ask questions'}
          disabled={!live}
          aria-label="Question"
          list="ask-examples"
        />
        <datalist id="ask-examples">
          {EXAMPLES.map((x) => (
            <option key={x} value={x} />
          ))}
        </datalist>
        <button type="submit" className="ask-go" disabled={!live || !text.trim() || ask.isPending}>
          {ask.isPending ? '…' : 'Ask'}
        </button>
      </form>
      <p className="ask-here">Here = {hereHint}. Select a stop, or move the step 4 time slider, to change it.</p>
    </section>
  );
}
