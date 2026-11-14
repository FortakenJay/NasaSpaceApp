import type { Stop } from '../api';

interface Props {
  stops: Stop[];
  /** Stops left out of the plan. */
  skippedIds: string[];
  selectedId: string | null;
  adding: boolean;
  /** No more stops can be added (limit reached, or the planner service is not running). */
  canAdd: boolean;
  problem: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
  onAdding: (adding: boolean) => void;
  onRename: (id: string, name: string) => void;
  onRemove: (id: string) => void;
}

/** Step 1: every stop on one list. Tick the ones to visit; add your own by clicking the map (they are saved). */
export function StopList({ stops, skippedIds, selectedId, adding, canAdd, problem, onSelect, onToggle, onAdding, onRename, onRemove }: Props) {
  const start = stops.find((s) => s.kind === 'start');
  const visitable = stops.filter((s) => s.kind !== 'start');
  return (
    <>
      {start && (
        <p className="note first">
          The walk starts and ends at the rover (<b>{start.id}</b>, green on the map). Tick the stops to visit.
        </p>
      )}
      <ol className="stops">
        {visitable.map((s) => {
          const selected = s.id === selectedId;
          return (
            <li key={s.id} className={selected ? 'active' : undefined}>
              <input
                type="checkbox"
                checked={!skippedIds.includes(s.id)}
                onChange={() => onToggle(s.id)}
                aria-label={`Visit ${s.id}, ${s.name}`}
              />
              <button type="button" className="stop" aria-pressed={selected} onClick={() => onSelect(s.id)}>
                <b className={s.kind === 'user' ? 'mine' : undefined}>{s.id}</b>
                <span>{s.name}</span>
              </button>
              {selected && s.kind === 'stop' && s.science && <p className="stop-detail">{s.science}</p>}
              {selected && s.kind === 'user' && (
                <div className="stop-detail">
                  <label>
                    Name
                    <input
                      key={s.name}
                      defaultValue={s.name}
                      maxLength={200}
                      onBlur={(e) => {
                        const name = e.target.value.trim();
                        if (name && name !== s.name) onRename(s.id, name);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.currentTarget.blur();
                      }}
                    />
                  </label>
                  <p className="note">Drag the purple point on the map to move this stop.</p>
                  <button type="button" className="link" onClick={() => onRemove(s.id)}>
                    Remove this stop
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <button type="button" className={adding ? 'secondary on' : 'secondary'} onClick={() => onAdding(!adding)} disabled={!canAdd && !adding}>
        {adding ? 'Done adding stops' : 'Add a stop on the map'}
      </button>
      {adding && <p className="callout">Click the ground where the crew should stop. Each stop is saved straight away.</p>}
      {problem && <p className="problem">{problem}</p>}
    </>
  );
}
