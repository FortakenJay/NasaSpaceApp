import { describeError, useSpaceWeather } from '../api';

const BASELINE = 'Baseline surface dose (MSL RAD): 0.21 mGy/day.';

export function SpaceWeatherPanel({ live }: { live: boolean }) {
  const status = useSpaceWeather(live);
  let level = 'Checking…';
  let detail = '';
  let dot = '';
  if (!live) {
    level = 'Not available offline';
    detail = BASELINE;
  } else if (status.data) {
    level = status.data.level;
    detail = status.data.reason;
    dot = status.data.level;
  } else if (status.error) {
    level = 'Not computed';
    detail = `${describeError(status.error, 'Go/no-go')} ${BASELINE}`;
  }
  return (
    <section>
      <h2>Space weather</h2>
      <div className="status">
        <span className={`dot ${dot}`} />
        <span>{level}</span>
      </div>
      <p className="note">{detail}</p>
    </section>
  );
}
