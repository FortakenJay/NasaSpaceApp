// State and server calls for Bases: listing, picking a new one on the map, downloading it, focusing and deleting.
// App passes the results to BasePanel (the sheet) and MarsMap (markers, footprints, the pick point).
import { useCallback, useState } from 'react';
import {
  describeError,
  useBaseLookup,
  useBases,
  useCancelBase,
  useCreateBase,
  useDeleteBase,
  useFocusBase,
  useFootprints,
  useResumeBase,
} from '../api';
import type { BaseInfo } from '../api';
import { formatBytes } from '../format';
import type { BasePanelProps } from './BasePanel';

export function useBaseWorkflow(live: boolean, siteId: string, onPickStart: () => void) {
  const bases = useBases(live);
  const [picking, setPickingState] = useState(false);
  const [pickPoint, setPickPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [selectedBaseId, setSelectedBaseId] = useState<string | null>(null);
  const footprints = useFootprints(live && picking);
  const lookup = useBaseLookup(picking ? pickPoint : null);
  const createBase = useCreateBase();
  const cancelBase = useCancelBase();
  const resumeBase = useResumeBase();
  const focusBase = useFocusBase();
  const deleteBase = useDeleteBase();

  const setPicking = useCallback((on: boolean) => {
    setPickingState(on);
    setPickPoint(null);
    if (on) {
      setSelectedBaseId(null);
      onPickStart();
    }
  }, [onPickStart]);

  const list = bases.data?.bases ?? [];
  const focusedId = bases.data?.focused ?? siteId;
  const busy = focusBase.isPending || deleteBase.isPending || resumeBase.isPending;
  const selectedBase: BaseInfo | null = list.find((b) => b.id === selectedBaseId) ?? null;

  const onFocus = (id: string) => focusBase.mutate(id);
  const onResume = (id: string) => resumeBase.mutate(id);
  const onDelete = (b: BaseInfo) => {
    const size = formatBytes(b.size_bytes);
    const msg = `Delete the Base “${b.name}”? Its downloaded data${size ? ` (${size})` : ''}, stops, plans and field notes `
      + 'will be removed. This cannot be undone.';
    if (window.confirm(msg)) deleteBase.mutate(b.id, { onSuccess: () => setSelectedBaseId(null) });
  };

  const failures: [unknown, string][] = [
    [createBase.error, 'Creating the Base'], [focusBase.error, 'Switching Base'], [deleteBase.error, 'Deleting the Base'],
    [resumeBase.error, 'Resuming the download'], [cancelBase.error, 'Cancelling'],
  ];
  const failed = failures.find(([e]) => e);
  const panel: BasePanelProps = {
    live,
    bases: list,
    focusedId,
    job: bases.data?.job ?? null,
    picking,
    onPicking: setPicking,
    lookup: lookup.data,
    lookupPending: lookup.isFetching,
    lookupError: lookup.isError ? describeError(lookup.error, 'Checking that spot') : null,
    footprintsPending: picking && footprints.isPending,
    creating: createBase.isPending,
    problem: failed ? describeError(failed[0], failed[1]) : null,
    busy,
    onCreate: (name, productId) => {
      if (!pickPoint) return;
      createBase.mutate({ lat: pickPoint.lat, lon: pickPoint.lon, name, product_id: productId }, { onSuccess: () => setPicking(false) });
    },
    onCancelJob: (id) => cancelBase.mutate(id),
    onFocus,
    onDelete,
    onResume,
  };
  return {
    panel,
    picking,
    lookupFetching: lookup.isFetching,
    selectedBase,
    focusedId,
    busy,
    onFocus,
    onDelete,
    onResume,
    closeCard: () => setSelectedBaseId(null),
    map: {
      bases: list,
      focusedBaseId: focusedId,
      selectedBaseId,
      onSelectBase: setSelectedBaseId,
      picking,
      footprints: footprints.data ?? null,
      pickPoint,
      pickBox: lookup.data?.bbox ?? null,
      onPickBase: (lat: number, lon: number) => setPickPoint({ lat, lon }),
    },
  };
}
