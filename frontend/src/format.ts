// Plain-language number formatting shared by the panels.

/** 211.5 -> "3 h 32 min"; 45 -> "45 min"; 120 -> "2 h". */
export function formatMinutes(minutes: number): string {
  const total = Math.max(Math.round(minutes), 0);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${String(m).padStart(2, '0')} min`;
}

export function formatHours(hours: number): string {
  return formatMinutes(hours * 60);
}

/** ["S2", "S3", "S4"] -> "S2, S3 and S4". */
export function formatList(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}
