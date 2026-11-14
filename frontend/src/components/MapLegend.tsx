interface Props {
  mapView: string;
  safeZoneOn: boolean;
  hasRoute: boolean;
  hasAdded: boolean;
  /** Walk limit in metres if the ring is drawn. */
  walkLimitM: number | null;
  /** The dashed straight-line preview is on the map (site stops, nothing planned yet). */
  showStraight: boolean;
  /** One sentence about the terrain layer being shown, from the server. */
  note: string;
}

const SCALES: Record<string, { title: string; className: string; from: string; to: string }> = {
  slope5: { title: 'Slope', className: 'scale turbo', from: 'flat', to: '30° or more' },
  roughness: { title: 'Roughness (rocks and ledges)', className: 'scale magma', from: 'smooth', to: '0.8 m or more' },
  ti: { title: 'Thermal inertia', className: 'scale viridis', from: 'loose sand', to: 'bedrock' },
};

/** Key for whatever is drawn on the map right now. */
export function MapLegend({ mapView, safeZoneOn, hasRoute, hasAdded, walkLimitM, showStraight, note }: Props) {
  const scale = SCALES[mapView];
  return (
    <details className="legend" open>
      <summary>Map key</summary>
      <ul>
        <li>
          <span className="swatch dot-start" /> Rover (start and finish)
        </li>
        <li>
          <span className="swatch dot-stop" /> Science stop
        </li>
        {hasAdded && (
          <li>
            <span className="swatch dot-picked" /> Stop you added (drag to move)
          </li>
        )}
        {hasRoute && (
          <li>
            <span className="swatch line" /> Planned route
          </li>
        )}
        {showStraight && (
          <li>
            <span className="swatch line dashed" /> Straight line (not planned yet)
          </li>
        )}
        {walkLimitM !== null && (
          <li>
            <span className="swatch line dotted" /> Farthest allowed from the rover ({(walkLimitM / 1000).toFixed(0)} km)
          </li>
        )}
        {mapView === 'nogo' && (
          <li>
            <span className="swatch box-nogo" /> Off limits: too steep or too rough
          </li>
        )}
        {safeZoneOn && (
          <li>
            <span className="swatch box-safe" /> Can still walk home (orange: barely)
          </li>
        )}
      </ul>
      {scale && (
        <div className="scale-block">
          <span>{scale.title}</span>
          <span className={scale.className} />
          <span className="scale-ends">
            <span>{scale.from}</span>
            <span>{scale.to}</span>
          </span>
        </div>
      )}
      {note && <p className="legend-note">{note}</p>}
    </details>
  );
}
