import type { CostModel, StopOrder } from '../api';

interface Props {
  cost: CostModel;
  order: StopOrder;
  onCost: (cost: CostModel) => void;
  onOrder: (order: StopOrder) => void;
  onPlan: () => void;
  pending: boolean;
  /** Why planning is not possible right now (shown instead of enabling the button), or null. */
  blocked: string | null;
  error: string | null;
  planned: boolean;
}

/** Step 2: one button, with the two tuning choices tucked under "Options". */
export function PlanPanel({ cost, order, onCost, onOrder, onPlan, pending, blocked, error, planned }: Props) {
  return (
    <>
      <button type="button" className="primary" onClick={onPlan} disabled={pending || blocked !== null}>
        {pending ? 'Finding the safest route…' : planned ? 'Plan route again' : 'Plan route'}
      </button>
      {blocked && <p className="note">{blocked}</p>}
      {pending && <p className="note">Right after the service starts this can take up to half a minute while it loads the terrain.</p>}
      {error && <p className="problem">{error}</p>}
      <details className="options">
        <summary>Options</summary>
        <label>
          Prefer a route that
          <select value={cost} onChange={(e) => onCost(e.target.value as CostModel)}>
            <option value="metabolic">costs the least effort (metabolic energy)</option>
            <option value="weighted">stays on the gentlest ground (hazard score)</option>
          </select>
        </label>
        <label>
          Visit the stops
          <select value={order} onChange={(e) => onOrder(e.target.value as StopOrder)}>
            <option value="fixed">in the order listed</option>
            <option value="optimize">in whichever order is cheapest</option>
          </select>
        </label>
      </details>
    </>
  );
}
