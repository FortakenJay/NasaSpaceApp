import type { PlanResult as Plan } from '../api';
import { formatHours, formatMinutes } from '../format';
import { RouteProfileChart } from './RouteProfileChart';

const RULE_NAMES: Record<string, string> = {
  max_duration: 'Time outside',
  max_distance_from_rover: 'Distance from the rover',
  walkback_reserve: 'Walk-home reserve',
  unreachable: 'No walkable route',
  radio_shadow: 'Radio',
  storm_shelter: 'Storm shelter',
  marginal_ground: 'Uncertain ground',
};

interface Props {
  result: Plan | null;
  usableH: number;
}

/** Step 3: the plan in four numbers, a verdict, the terrain profile and the timeline. */
export function PlanResult({ result, usableH }: Props) {
  if (!result) return <p className="note">Press “Plan route” to see the distance, the time outside and the safety checks.</p>;
  const s = result.summary;
  const num = (key: string) => Number(s[key] ?? 0);
  const broken = result.violations.filter((v) => v.severity === 'no-go');
  const cautions = result.violations.filter((v) => v.severity !== 'no-go');
  const workingH = num('duration_h') - num('walking_h');
  return (
    <>
      <p className={broken.length > 0 ? 'verdict nogo' : cautions.length > 0 ? 'verdict caution' : 'verdict go'}>
        {broken.length > 0
          ? `This walk breaks ${broken.length} limit${broken.length > 1 ? 's' : ''}.`
          : cautions.length > 0
            ? 'This walk is inside the limits, with warnings.'
            : 'This walk stays inside every limit.'}
      </p>
      {result.violations.length > 0 && (
        <ul className="violations">
          {result.violations.map((v) => (
            <li key={`${v.rule}-${v.where}-${v.detail}`} className={v.severity}>
              <b>
                {RULE_NAMES[v.rule] ?? v.rule}
                {v.where ? ` at ${v.where}` : ''}:
              </b>{' '}
              {v.detail}
            </li>
          ))}
        </ul>
      )}
      <dl className="tiles">
        <div>
          <dt>Distance</dt>
          <dd>{num('distance_km').toFixed(2)} km</dd>
          <dd className="sub">there and back</dd>
        </div>
        <div>
          <dt>Time outside</dt>
          <dd>{formatHours(num('duration_h'))}</dd>
          <dd className="sub">
            {formatHours(num('walking_h'))} walking, {formatHours(workingH)} at stops
          </dd>
        </div>
        <div>
          <dt>Energy used</dt>
          <dd>{num('energy_budget_used_pct')}%</dd>
          <dd className="sub">
            of the budget ({num('energy_kj').toLocaleString()} kJ, about {num('o2_kg_est')} kg of oxygen)
          </dd>
        </div>
        <div>
          <dt>Spare time</dt>
          <dd>{formatMinutes(num('min_walkback_margin_min'))}</dd>
          <dd className="sub">smallest margin to still walk home</dd>
        </div>
      </dl>
      <RouteProfileChart profile={result.profile} />
      <p className="note">
        Steepest step on the route: {num('max_grade_deg')}° (limit 20°). Steepest ground crossed: {num('max_slope_deg')}° (areas
        above 25° are off limits).
      </p>
      {s.radio_shadow_min !== undefined && (
        <p className="note">
          Out of radio contact with the rover: {formatMinutes(num('radio_shadow_min'))} of the walk
          {num('radio_shadow_min') > 0 ? ` (longest stretch ${formatMinutes(num('radio_longest_shadow_min'))})` : ''}. Solar
          storm: the walk home never takes longer than {formatMinutes(num('shelter_max_walk_home_min'))}
          {num('shelter_beyond_min') > 0
            ? `, but for ${formatMinutes(num('shelter_beyond_min'))} it is longer than the ${num('shelter_lead_min')} min warning.`
            : `, inside the ${num('shelter_lead_min')} min warning everywhere.`}{' '}
          {s.limiting_consumable ? `Runs out first: ${String(s.limiting_consumable).toLowerCase()} (${s.consumables_used} used).` : ''}
        </p>
      )}
      <details className="options">
        <summary>Timeline, stop by stop</summary>
        <table className="timeline">
          <thead>
            <tr>
              <th>Stop</th>
              <th>Arrive</th>
              <th>Leave</th>
              <th>Walk home</th>
              <th>Leave by</th>
            </tr>
          </thead>
          <tbody>
            {result.timeline.map((w) => (
              <tr key={`${w.id}-${w.kind}`}>
                <td>{w.id}</td>
                <td>{formatMinutes(w.arrive_min)}</td>
                <td>{w.kind === 'end' ? '' : formatMinutes(w.depart_min)}</td>
                <td>{w.kind === 'stop' ? formatMinutes(w.walkback_min) : ''}</td>
                <td>{w.kind === 'stop' ? formatMinutes(usableH * 60 - w.walkback_min) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          “Leave by” is the latest time since leaving the rover at which the crew can still walk home from that stop with the
          reserve untouched.
        </p>
      </details>
    </>
  );
}
