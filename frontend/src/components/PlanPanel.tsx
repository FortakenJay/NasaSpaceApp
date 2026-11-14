import { useState } from 'react';
import { describeError, useComputePlan, usePlans, useSavePlan } from '../api';
import type { CostModel, PlanResult, Stop, StopOrder } from '../api';

interface Props {
  live: boolean;
  stops: Stop[];
  onRoute: (route: GeoJSON.FeatureCollection | null) => void;
}

export function PlanPanel({ live, stops, onRoute }: Props) {
  const [cost, setCost] = useState<CostModel>('metabolic');
  const [order, setOrder] = useState<StopOrder>('fixed');
  const [name, setName] = useState('');
  const compute = useComputePlan();
  const save = useSavePlan();
  const plans = usePlans(live);
  const stopIds = stops.filter((s) => s.kind === 'stop').map((s) => s.id);

  const run = () =>
    compute.mutate({ cost, order, stop_ids: stopIds }, { onSuccess: (r: PlanResult) => onRoute(r.route) });

  const saveRequest = () =>
    save.mutate({ name: name.trim(), cost, order, stop_ids: stopIds }, { onSuccess: () => setName('') });

  return (
    <section>
      <h2>Plan EVA</h2>
      <div className="controls">
        <label>
          Cost model
          <select value={cost} onChange={(e) => setCost(e.target.value as CostModel)}>
            <option value="metabolic">Metabolic (SEXTANT-style)</option>
            <option value="weighted">Weighted hazard score</option>
          </select>
        </label>
        <label>
          Stop order
          <select value={order} onChange={(e) => setOrder(e.target.value as StopOrder)}>
            <option value="fixed">Fixed science order</option>
            <option value="optimize">Optimize order</option>
          </select>
        </label>
        <button type="button" onClick={run} disabled={!live || compute.isPending}>
          {compute.isPending ? 'Planning…' : 'Plan route'}
        </button>
      </div>
      {!live && <p className="note">Start the API (python -m marswalk serve) to plan and save routes.</p>}
      {compute.isError && <p className="note">{describeError(compute.error, 'Route planning')}</p>}
      {compute.data && (
        <p className="note">
          {Object.entries(compute.data.summary).map(([k, v]) => `${k}: ${v}`).join(' · ')}
        </p>
      )}

      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          saveRequest();
        }}
      >
        <input
          aria-label="Plan name"
          placeholder="Plan name (optional)"
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
          disabled={!live}
        />
        <button type="submit" className="secondary" disabled={!live || save.isPending}>
          Save request
        </button>
      </form>
      {save.isError && <p className="note">{describeError(save.error, 'Saving')}</p>}

      {live && (plans.data?.length ?? 0) > 0 && (
        <ul className="saved">
          {plans.data?.map((p) => (
            <li key={p.id}>
              <b>{p.name || 'Untitled plan'}</b>
              <small>
                {new Date(p.created_at).toLocaleString()} · {p.cost_model}, {p.stop_order} · {p.status}
              </small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
