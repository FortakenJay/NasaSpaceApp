interface Props {
  names: string[];
  visibility: Record<string, boolean>;
  onToggle: (name: string, visible: boolean) => void;
  overlaysPending: boolean;
}

export function LayerToggles({ names, visibility, onToggle, overlaysPending }: Props) {
  return (
    <section>
      <h2>Layers</h2>
      <div className="layers">
        {names.map((name) => (
          <label key={name}>
            <input
              type="checkbox"
              checked={visibility[name] ?? true}
              onChange={(e) => onToggle(name, e.target.checked)}
            />
            {name}
          </label>
        ))}
      </div>
      {overlaysPending && (
        <p className="note">Slope, roughness, thermal inertia and no-go overlays arrive with milestone M2.</p>
      )}
    </section>
  );
}
