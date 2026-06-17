import { useCallback, useRef, useState } from 'react';
import type { TemplateSlot } from './timeline';

const MAX_HISTORY = 40;

export function useSlotHistory(initial: TemplateSlot[] = []) {
  const [slots, setSlotsState] = useState<TemplateSlot[]>(initial);
  const pastRef = useRef<TemplateSlot[][]>([]);
  const futureRef = useRef<TemplateSlot[][]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const syncFlags = useCallback(() => {
    setCanUndo(pastRef.current.length > 0);
    setCanRedo(futureRef.current.length > 0);
  }, []);

  const setSlots = useCallback(
    (next: TemplateSlot[] | ((prev: TemplateSlot[]) => TemplateSlot[]), recordHistory = true) => {
      setSlotsState((prev) => {
        const resolved = typeof next === 'function' ? next(prev) : next;
        if (recordHistory && resolved !== prev) {
          pastRef.current = [...pastRef.current, prev].slice(-MAX_HISTORY);
          futureRef.current = [];
          syncFlags();
        }
        return resolved;
      });
    },
    [syncFlags]
  );

  const replaceSlots = useCallback(
    (next: TemplateSlot[], recordHistory = false) => {
      setSlots(next, recordHistory);
    },
    [setSlots]
  );

  const undo = useCallback(() => {
    setSlotsState((current) => {
      const past = pastRef.current;
      if (!past.length) return current;
      const previous = past[past.length - 1];
      pastRef.current = past.slice(0, -1);
      futureRef.current = [current, ...futureRef.current].slice(0, MAX_HISTORY);
      syncFlags();
      return previous;
    });
  }, [syncFlags]);

  const redo = useCallback(() => {
    setSlotsState((current) => {
      const future = futureRef.current;
      if (!future.length) return current;
      const [next, ...rest] = future;
      futureRef.current = rest;
      pastRef.current = [...pastRef.current, current].slice(-MAX_HISTORY);
      syncFlags();
      return next;
    });
  }, [syncFlags]);

  const resetHistory = useCallback(() => {
    pastRef.current = [];
    futureRef.current = [];
    syncFlags();
  }, [syncFlags]);

  return {
    slots,
    setSlots,
    replaceSlots,
    undo,
    redo,
    canUndo,
    canRedo,
    resetHistory,
  };
}
