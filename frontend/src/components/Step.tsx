import type { ReactNode } from 'react';

interface Props {
  n: number;
  title: string;
  /** A finished step shows a tick instead of its number. */
  done?: boolean;
  children: ReactNode;
}

/** One numbered step of the checklist. The numbers are a real sequence: stops, plan, check, walk home. */
export function Step({ n, title, done = false, children }: Props) {
  return (
    <section className={done ? 'step done' : 'step'}>
      <div className="step-num" aria-hidden="true">
        {done ? '✓' : n}
      </div>
      <div className="step-body">
        <h2>{title}</h2>
        {children}
      </div>
    </section>
  );
}
