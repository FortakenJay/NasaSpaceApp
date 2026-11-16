// Bases: every place the crew works from (Gale built in, others created from the HiRISE catalog), the one in focus,
// creating a new one (pick a point inside a HiRISE stereo footprint, check what it needs, download), and deleting.
import { useState } from 'react';
import type { BaseInfo, BaseJob, BaseLookup } from '../api';
import { formatBytes } from '../format';

function AlignmentBadge({ base }: { base: BaseInfo }) {
  if (base.kind === 'builtin') return <span className="badge ok">measured</span>;
  const q = base.alignment?.quality;
  if (!q) return null;
  const cls = q === 'good' ? 'ok' : q === 'fair' ? 'caution' : 'warn';
  const text = base.alignment?.source === 'file' ? 'not aligned' : `aligned: ${q}`;
  return <span className={`badge ${cls}`} title="How well the terrain lines up with the map photo">{text}</span>;
}

function baseSubtitle(b: BaseInfo): string {
  const size = b.kind === 'builtin' ? 'Built in' : b.status === 'ready' ? formatBytes(b.size_bytes) : b.status;
  const dose = b.radiation?.estimate && b.kind !== 'builtin' ? ` · ${b.radiation.gcr_mgy_per_day.toFixed(3)} mGy/day (estimate)` : '';
  return size + dose;
}

/** The small card next to a Base marker on the map. */
export function BaseCard({ base, focused, busy, onFocus, onDelete, onResume, onClose }: {
  base: BaseInfo;
  focused: boolean;
  busy: boolean;
  onFocus: (id: string) => void;
  onDelete: (b: BaseInfo) => void;
  onResume: (id: string) => void;
  onClose: () => void;
}) {
  const resumable = base.status === 'interrupted' || base.status === 'failed';
  return (
    <section className="base-card" aria-label={`Base ${base.name}`}>
      <button type="button" className="close" aria-label="Close" onClick={onClose}>×</button>
      <b>{base.name}</b>
      <small>
        {base.kind === 'builtin' ? 'Built in' : base.terrain_name || base.product_id}
        {base.status !== 'ready' ? ` · ${base.status}` : ''}
      </small>
      <div className="row">
        {focused && <span className="badge ok">in focus</span>}
        {!focused && base.status === 'ready' && <button type="button" onClick={() => onFocus(base.id)} disabled={busy}>Focus</button>}
        {resumable && <button type="button" onClick={() => onResume(base.id)} disabled={busy}>Resume</button>}
        {base.deletable && base.status !== 'creating' && (
          <button type="button" className="secondary danger" onClick={() => onDelete(base)} disabled={busy}>Delete</button>
        )}
      </div>
    </section>
  );
}

function BaseRow({ base, focused, live, busy, jobRunning, onFocus, onDelete, onResume }: {
  base: BaseInfo;
  focused: boolean;
  live: boolean;
  busy: boolean;
  jobRunning: boolean;
  onFocus: (id: string) => void;
  onDelete: (b: BaseInfo) => void;
  onResume: (id: string) => void;
}) {
  const ready = base.status === 'ready';
  return (
    <li className={focused ? 'focused' : ''}>
      <button
        type="button"
        className="base-pick"
        onClick={() => onFocus(base.id)}
        disabled={!live || !ready || focused || busy}
        aria-pressed={focused}
        title={focused ? 'The planner is working on this Base' : 'Focus this Base'}
      >
        <b>{base.name}</b>
        <small>{baseSubtitle(base)}</small>
      </button>
      <AlignmentBadge base={base} />
      {(base.status === 'interrupted' || base.status === 'failed') && (
        <button type="button" className="secondary" onClick={() => onResume(base.id)} disabled={busy || jobRunning}>Resume</button>
      )}
      {base.deletable && base.status !== 'creating' && (
        <button type="button" className="secondary danger" onClick={() => onDelete(base)} disabled={busy} aria-label={`Delete ${base.name}`}>
          Delete
        </button>
      )}
    </li>
  );
}

function JobProgress({ job, canFocus, onCancel, onFocus }: {
  job: BaseJob;
  canFocus: boolean;
  onCancel: () => void;
  onFocus: () => void;
}) {
  const pct = Math.round(job.fraction * 100);
  return (
    <div className="job" aria-live="polite">
      <div className="job-head">
        <b>{job.name}</b>
        <span>{job.status === 'running' ? `${pct}%` : job.status}</span>
      </div>
      <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <ol className="job-steps">
        {job.steps.map((s) => (
          <li key={s.key} className={s.state}>
            {s.label}
            {s.detail ? <small> · {s.detail}</small> : null}
          </li>
        ))}
      </ol>
      {job.error && job.status !== 'cancelled' && <p className="problem">{job.error}</p>}
      <div className="row">
        {job.status === 'running' && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}
        {job.status === 'ready' && canFocus && <button type="button" onClick={onFocus}>Focus {job.name}</button>}
      </div>
    </div>
  );
}

function LookupForm({ lookup, creating, onCreate, onCancel }: {
  lookup: BaseLookup;
  creating: boolean;
  onCreate: (name: string, productId: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState('');
  const [productId, setProductId] = useState('');
  const chosen = lookup.candidates.find((c) => c.product_id === productId) ?? lookup.candidates[0];
  const lowDisk = lookup.free_bytes < lookup.est_bytes;
  if (!chosen) return null;
  return (
    <form
      className="lookup"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate(name.trim() || chosen.name || 'New Base', chosen.product_id);
      }}
    >
      <label>
        Name
        <input value={name} maxLength={100} placeholder={chosen.name || 'New Base'} onChange={(e) => setName(e.target.value)} />
      </label>
      {lookup.candidates.length > 1 && (
        <label>
          Terrain
          <select value={chosen.product_id} onChange={(e) => setProductId(e.target.value)}>
            {lookup.candidates.map((c) => (
              <option key={c.product_id} value={c.product_id}>
                {c.name || c.product_id} ({(c.edge_m / 1000).toFixed(1)} km from the strip edge)
              </option>
            ))}
          </select>
        </label>
      )}
      <small>
        {lookup.lat.toFixed(4)}°, {lookup.lon.toFixed(4)}° · download about {formatBytes(lookup.est_bytes)} ({formatBytes(lookup.free_bytes)} free)
        {lookup.ti_tile ? '' : ' · no thermal inertia here'}
      </small>
      {lookup.warnings.map((w) => <p key={w} className="hint">{w}</p>)}
      {lowDisk && <p className="problem">Not enough free disk space for this Base.</p>}
      <div className="row">
        <button type="submit" disabled={creating || lowDisk}>{creating ? 'Starting…' : 'Download and create'}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export interface BasePanelProps {
  live: boolean;
  bases: BaseInfo[];
  focusedId: string;
  job: BaseJob | null;
  picking: boolean;
  onPicking: (on: boolean) => void;
  lookup: BaseLookup | undefined;
  lookupPending: boolean;
  lookupError: string | null;
  footprintsPending: boolean;
  creating: boolean;
  problem: string | null;
  busy: boolean;
  onCreate: (name: string, productId: string) => void;
  onCancelJob: (id: string) => void;
  onFocus: (id: string) => void;
  onDelete: (b: BaseInfo) => void;
  onResume: (id: string) => void;
}

function PickPanel(p: BasePanelProps) {
  return (
    <div className="pick">
      <p className="callout">
        {p.footprintsPending
          ? 'Loading where HiRISE 1 m stereo terrain exists…'
          : 'Click inside a cyan outline: those are the places with 1 m HiRISE stereo terrain, where a suited walk can be planned.'}
      </p>
      {p.lookupPending && <p className="hint">Checking that spot…</p>}
      {p.lookupError && <p className="problem">{p.lookupError}</p>}
      {p.lookup ? (
        <LookupForm lookup={p.lookup} creating={p.creating} onCreate={p.onCreate} onCancel={() => p.onPicking(false)} />
      ) : (
        <button type="button" className="secondary" onClick={() => p.onPicking(false)}>Stop picking</button>
      )}
    </div>
  );
}

export function BasePanel(p: BasePanelProps) {
  const job = p.job;
  const running = job?.status === 'running';
  // A finished job stays visible until its Base is the focused one (so "Focus" is one click away).
  const showJob = job !== null && job.status !== 'cancelled'
    && (running || (job.base_id !== p.focusedId && p.bases.some((b) => b.id === job.base_id)));
  return (
    <section className="bases">
      <ul className="base-list">
        {p.bases.map((b) => (
          <BaseRow key={b.id} base={b} focused={b.id === p.focusedId} live={p.live} busy={p.busy} jobRunning={running}
            onFocus={p.onFocus} onDelete={p.onDelete} onResume={p.onResume} />
        ))}
      </ul>
      {showJob && job && (
        <JobProgress job={job} canFocus={job.base_id !== p.focusedId}
          onCancel={() => p.onCancelJob(job.base_id)} onFocus={() => p.onFocus(job.base_id)} />
      )}
      {p.picking ? <PickPanel {...p} /> : (
        <button type="button" onClick={() => p.onPicking(true)} disabled={!p.live || running}>New Base</button>
      )}
      {p.problem && <p className="problem">{p.problem}</p>}
    </section>
  );
}
