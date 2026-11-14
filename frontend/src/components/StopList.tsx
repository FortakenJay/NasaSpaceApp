import type { Stop } from '../api';

interface Props {
  stops: Stop[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function StopList({ stops, selectedId, onSelect }: Props) {
  return (
    <section>
      <h2>Stops</h2>
      <ol className="stops">
        {stops.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              className={s.id === selectedId ? 'stop active' : 'stop'}
              aria-pressed={s.id === selectedId}
              onClick={() => onSelect(s.id)}
            >
              <b>{s.id}</b>
              {s.name}
              <small>{s.science || (s.kind === 'start' ? 'EVA start / rover parking' : '')}</small>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
