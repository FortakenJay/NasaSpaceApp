export interface MapView {
  key: string;
  label: string;
}

interface Props {
  views: MapView[];
  value: string;
  onChange: (key: string) => void;
}

/** "Show on the map" switch floating over the map: the photo, or one terrain layer at a time. */
export function LayerToggles({ views, value, onChange }: Props) {
  return (
    <div className="map-views" role="group" aria-label="What the map shows">
      <span className="map-views-title">Show</span>
      {views.map((v) => (
        <button key={v.key} type="button" aria-pressed={v.key === value} onClick={() => onChange(v.key)}>
          {v.label}
        </button>
      ))}
    </div>
  );
}
