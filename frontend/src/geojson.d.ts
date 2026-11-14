// Minimal GeoJSON types for the plan payload (avoids an extra @types dependency).
declare namespace GeoJSON {
  type Position = [number, number] | [number, number, number];
  interface LineString { type: 'LineString'; coordinates: Position[] }
  interface Feature { type: 'Feature'; geometry: LineString; properties: Record<string, unknown> | null }
  interface FeatureCollection { type: 'FeatureCollection'; features: Feature[] }
}
