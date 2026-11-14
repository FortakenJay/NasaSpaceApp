import { describeError, useSpaceWeather } from '../api';

const HEADLINE = { GO: 'Clear to go outside', CAUTION: 'Go with caution', 'NO-GO': 'Stay inside' } as const;

/** Radiation go/no-go from NASA DONKI (CME arrivals predicted at Mars, particle events, flares) plus the RAD dose. */
export function SpaceWeatherPanel({ live }: { live: boolean }) {
  const status = useSpaceWeather(live);
  const d = status.data;
  let headline = 'Checking the Sun…';
  let detail = 'Asking NASA’s space-weather database (DONKI). This takes up to 15 seconds; the answer is then kept for 30 minutes.';
  if (!live) {
    headline = 'Not checked (offline demo)';
    detail = 'Start the planner service to check NASA’s space-weather database.';
  } else if (d) {
    headline = HEADLINE[d.level];
    detail = d.reason;
  } else if (status.error) {
    headline = 'Could not check';
    detail = describeError(status.error, 'The space-weather check');
  }
  return (
    <details className={`weather ${d?.level ?? ''}`}>
      <summary>
        <span className="dot" aria-hidden="true" />
        <span className="weather-title">
          Space weather: <b>{headline}</b>
        </span>
      </summary>
      {detail && <p className="note">{detail}</p>}
      {d && (
        <>
          <p className="note">
            Radiation dose for a full {d.eva_duration_h} h walk: {d.eva_dose_mgy.toFixed(2)} mGy, from the Curiosity RAD
            surface baseline of {d.baseline_dose_mgy_per_day} mGy per day (cosmic rays only).
          </p>
          {d.mars_arrivals.map((a) => (
            <p className="note" key={a.arrival}>
              Solar eruption predicted to reach Mars {a.arrival.slice(0, 16).replace('T', ' ')} UTC (
              {a.glancing ? 'glancing blow' : 'direct hit'},{' '}
              {a.hours_from_now >= 0 ? `in ${a.hours_from_now.toFixed(0)} h` : `${(-a.hours_from_now).toFixed(0)} h ago`}).
            </p>
          ))}
          {d.notes.map((n) => (
            <p className="note" key={n}>
              {n}
            </p>
          ))}
          <p className="note">
            {d.data_ok
              ? `Source: NASA DONKI, checked at ${new Date(d.checked_at).toLocaleTimeString()}. Particle events in the last 7 days: ${d.recent_sep_events}. Strongest flare in 3 days: ${d.strongest_flare || 'none'}. Flares and particle events are measured near Earth, so they are only a hint for Mars.`
              : `${d.source}. See “NASA data connections” at the bottom of this sheet.`}
          </p>
        </>
      )}
    </details>
  );
}
