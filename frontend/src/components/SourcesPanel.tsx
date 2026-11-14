import { describeError, useRefreshSources, useSources } from '../api';
import type { SourceFeed } from '../api';
import { formatMinutes } from '../format';

function feedLine(f: SourceFeed): string {
  const age = f.age_s === null ? '' : formatMinutes(f.age_s / 60);
  if (f.state === 'fresh') return 'Just received from NASA.';
  if (f.state === 'cached') return `Reusing the answer from ${age} ago. Next request in ${formatMinutes((f.fresh_for_s ?? 0) / 60)}.`;
  if (f.state === 'stale') return `NASA did not answer, so the copy from ${age} ago is in use.`;
  return f.retry_in_s ? `No answer yet. Trying again in ${formatMinutes(f.retry_in_s / 60)}.` : 'No answer yet.';
}

/** One place that shows every request MarsWalk makes to NASA's web APIs, and how many it avoided. */
export function SourcesPanel({ live }: { live: boolean }) {
  const sources = useSources(live);
  const refresh = useRefreshSources();
  const s = sources.data;
  if (!live) return null;
  const saved = s ? s.stats.served_from_cache + s.stats.served_stale + s.stats.skipped_backing_off + s.stats.skipped_low_budget : 0;
  return (
    <details className="more" onToggle={(e) => e.currentTarget.open && void sources.refetch()}>
      <summary>NASA data connections</summary>
      {sources.isError && <p className="problem">{describeError(sources.error, 'Reading the connection status')}</p>}
      {s && (
        <>
          <p className="note">
            Every request to NASA goes through one client that keeps answers for 30 minutes, reuses the last good copy when
            NASA is slow, and waits before retrying a feed that failed.
          </p>
          <dl className="tiles small">
            <div>
              <dt>Requests sent</dt>
              <dd>{s.stats.requests_sent}</dd>
            </div>
            <div>
              <dt>Requests avoided</dt>
              <dd>{saved}</dd>
            </div>
          </dl>
          <ul className="feeds">
            {s.feeds.length === 0 && <li>Nothing has been asked yet.</li>}
            {s.feeds.map((f) => (
              <li key={f.name} className={f.state}>
                <b>{f.label}</b>
                {f.required ? '' : ' (optional)'}
                <small>{feedLine(f)}</small>
                {f.error && <small className="why">{f.error}</small>}
              </li>
            ))}
          </ul>
          <p className="note">
            {s.key === 'personal'
              ? `Using your own NASA key (${s.key_env} in .env).`
              : `Using NASA’s shared demo key, about 30 requests an hour. Put your own in .env as ${s.key_env} for 1,000.`}
            {s.rate_limit.remaining !== null && ` Requests left this hour: ${s.rate_limit.remaining} of ${s.rate_limit.limit ?? '?'}.`}
          </p>
          <button type="button" className="secondary" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            {refresh.isPending ? 'Asking NASA…' : 'Ask NASA again now'}
          </button>
          {refresh.isError && <p className="problem">{describeError(refresh.error, 'Asking NASA')}</p>}
        </>
      )}
    </details>
  );
}
