import { useState } from 'react';
import { describeError, useAddObservation, useObservations } from '../api';
import type { Stop } from '../api';

/** Field log for the selected stop: notes and sample IDs, stored in the DB through /api. */
export function StopLog({ stop, live }: { stop: Stop; live: boolean }) {
  const log = useObservations(stop.id, live);
  const add = useAddObservation(stop.id);
  const [note, setNote] = useState('');
  const [sampleId, setSampleId] = useState('');

  return (
    <section>
      <h2>
        Field log · {stop.id} {stop.name}
      </h2>
      {!live && <p className="note">The field log needs the API.</p>}
      {live && (
        <form
          className="log-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!note.trim()) return;
            add.mutate(
              { note: note.trim(), sample_id: sampleId.trim() || undefined },
              {
                onSuccess: () => {
                  setNote('');
                  setSampleId('');
                },
              },
            );
          }}
        >
          <textarea
            aria-label="Observation"
            placeholder="Observation"
            rows={2}
            maxLength={4000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="inline-form">
            <input
              aria-label="Sample ID"
              placeholder="Sample ID (optional)"
              maxLength={64}
              value={sampleId}
              onChange={(e) => setSampleId(e.target.value)}
            />
            <button type="submit" disabled={add.isPending || !note.trim()}>
              Log
            </button>
          </div>
          {add.isError && <p className="note">{describeError(add.error, 'Logging')}</p>}
        </form>
      )}
      {log.isError && <p className="note">{describeError(log.error, 'Field log')}</p>}
      {log.data?.length === 0 && <p className="note">No observations yet.</p>}
      <ul className="log">
        {log.data?.map((o) => (
          <li key={o.id}>
            <small>
              {new Date(o.created_at).toLocaleString()} · {o.author}
              {o.sample_id ? ` · sample ${o.sample_id}` : ''}
            </small>
            <p>{o.note}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
