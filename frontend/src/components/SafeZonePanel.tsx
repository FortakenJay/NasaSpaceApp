import { useEffect, useRef, useState } from 'react';
import type { TimelineEntry } from '../api';
import { formatHours, formatList } from '../format';

interface Props {
  available: boolean;
  elapsedH: number;
  usableH: number;
  visible: boolean;
  timeline: TimelineEntry[] | null;
  onElapsed: (hours: number) => void;
  onVisible: (visible: boolean) => void;
}

const STEP_H = 0.1;
const round1 = (x: number) => Math.round(x * 10) / 10;

/** Step 4: the Apollo-style walk-back limit. Everywhere the crew can still walk home from, at a chosen time. */
export function SafeZonePanel({ available, elapsedH, usableH, visible, timeline, onElapsed, onVisible }: Props) {
  const [draft, setDraft] = useState<number | null>(null); // value while the slider is being dragged
  const [playing, setPlaying] = useState(false);
  const latest = useRef(elapsedH);
  const value = draft ?? elapsedH;

  useEffect(() => {
    latest.current = elapsedH;
  }, [elapsedH]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const next = Math.min(round1(latest.current + STEP_H), usableH);
      onElapsed(next);
      if (next >= usableH) setPlaying(false);
    }, 900);
    return () => window.clearInterval(id);
  }, [playing, usableH, onElapsed]);

  if (!available) return <p className="note">The safe zone appears once the terrain data is loaded.</p>;

  const commit = () => {
    if (draft === null) return;
    onElapsed(draft);
    setDraft(null);
    if (!visible) onVisible(true);
  };
  const play = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    // The zone only starts to shrink in the last hour or so, so start the replay there.
    if (elapsedH >= usableH - STEP_H || elapsedH < usableH - 1.2) onElapsed(round1(Math.max(usableH - 1.2, 0)));
    onVisible(true);
    setPlaying(true);
  };

  const leftMin = (usableH - value) * 60;
  const stops = timeline?.filter((w) => w.kind === 'stop') ?? [];
  const outside = stops.filter((w) => w.walkback_min > leftMin).map((w) => w.id);
  return (
    <>
      <p className="note">
        The green area on the map is everywhere the crew could still walk back to the rover from, keeping the oxygen reserve.
        It shrinks as time runs out.
      </p>
      <label className="slider">
        <span>
          Time since leaving the rover: <b>{formatHours(value)}</b>
        </span>
        <input
          type="range"
          min={0}
          max={usableH}
          step={STEP_H}
          value={value}
          onChange={(e) => setDraft(Number(e.target.value))}
          onPointerUp={commit}
          onKeyUp={commit}
          onBlur={commit}
        />
      </label>
      <div className="row">
        <button type="button" className="secondary" onClick={play}>
          {playing ? 'Pause' : 'Play the last hour'}
        </button>
        <label className="check">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          Show on map
        </label>
      </div>
      {stops.length === 0 ? (
        <p className="note">Plan a route to see which stops fall outside the zone.</p>
      ) : outside.length === 0 ? (
        <p className="verdict go">At {formatHours(value)} every planned stop is still inside the safe zone.</p>
      ) : (
        <p className="verdict nogo">
          At {formatHours(value)} the crew could no longer walk home in time from {formatList(outside)}.
        </p>
      )}
    </>
  );
}
