import { useEffect, useRef, useState } from 'react';
import { einkUrl } from '../api';
import { formatHours } from '../format';

interface Props {
  live: boolean;
  planId: string | null;
  /** Hours into the walk (shared with the step 4 slider). */
  elapsedH: number;
  /** When the plan is back at the rover, in hours. */
  endH: number | null;
  onElapsed: (hours: number) => void;
}

const FRAMES = 30; // a played walk shows this many screens

/** What the walker's e-ink screen shows at any moment of the planned walk, like a car navigation screen. */
export function SuitDisplayPanel({ live, planId, elapsedH, endH, onElapsed }: Props) {
  const [shown, setShown] = useState<string | null>(null); // the picture on screen; the next one loads behind it
  const [playing, setPlaying] = useState(false);
  const [large, setLarge] = useState(false);
  const latest = useRef(elapsedH);
  const t = endH === null ? 0 : Math.min(elapsedH, endH);
  const src = planId ? einkUrl(planId, t) : null;

  useEffect(() => {
    latest.current = elapsedH;
  }, [elapsedH]);

  // Swap pictures only once the new one has loaded, so a played walk does not flash.
  useEffect(() => {
    if (!src) return;
    const img = new Image();
    img.onload = () => setShown(src);
    img.src = src;
    return () => {
      img.onload = null;
    };
  }, [src]);

  useEffect(() => {
    if (!playing || endH === null) return;
    const id = window.setInterval(() => {
      const next = Math.min(latest.current + endH / FRAMES, endH);
      onElapsed(Math.round(next * 1000) / 1000);
      if (next >= endH) setPlaying(false);
    }, 1400);
    return () => window.clearInterval(id);
  }, [playing, endH, onElapsed]);

  if (!live || !planId || endH === null) {
    return <p className="note">Plan a walk to see what the suit’s screen would show along the way.</p>;
  }
  const play = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (elapsedH >= endH - 1e-3) onElapsed(0);
    setPlaying(true);
  };
  const picture = shown && (
    <img
      src={shown}
      width={800}
      height={480}
      alt={`Suit display ${formatHours(t)} into the walk: next stop, distance, oxygen left, walk home and turn-back time`}
    />
  );

  return (
    <>
      <p className="note first">
        A 7.5-inch e-ink screen on the suit: the next stop and how far it is, oxygen left before the reserve, the walk home
        and when to turn back. It follows the time on the slider.
      </p>
      <button type="button" className="eink-frame" onClick={() => setLarge(true)} aria-label="Show the suit display larger">
        {picture}
      </button>
      <label className="slider">
        <span>
          Time since leaving the rover: <b>{formatHours(t)}</b>
        </span>
        <input
          type="range"
          min={0}
          max={endH}
          step={1 / 60}
          value={t}
          onChange={(e) => onElapsed(Number(e.target.value))}
        />
      </label>
      <div className="row">
        <button type="button" className="secondary" onClick={play}>
          {playing ? 'Pause' : 'Play the walk'}
        </button>
        <a className="note" href={einkUrl(planId, t).replace('.png', '.bin')} download="suit-display.bin">
          Download for an ESP32
        </a>
      </div>
      {large && (
        <div className="eink-large" role="dialog" aria-label="Suit display" onClick={() => setLarge(false)}>
          {picture}
          <p>Click anywhere to close</p>
        </div>
      )}
    </>
  );
}
