import { useEffect, useMemo, useState } from 'react';
import {
  fetchTimelineThumbnailProfiles,
  sampleIntervalForZoom,
  selectThumbnailsForZoom,
  type TimelineThumbnail,
  type TimelineThumbnailProfiles,
} from '@/lib/timelineThumbnails';

export function useTimelineThumbnails(templateId?: string | null, pxPerSec = 48) {
  const [profiles, setProfiles] = useState<TimelineThumbnailProfiles>({});
  const [duration, setDuration] = useState(0);
  const [status, setStatus] = useState<'ready' | 'processing'>('processing');
  const [loading, setLoading] = useState(false);

  const sampleIntervalSec = useMemo(() => sampleIntervalForZoom(pxPerSec), [pxPerSec]);

  const needHigh = pxPerSec >= 160;

  useEffect(() => {
    if (!templateId) {
      setProfiles({});
      setDuration(0);
      setStatus('processing');
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    void fetchTimelineThumbnailProfiles(templateId, { includeHigh: needHigh }).then((payload) => {
      if (cancelled) return;
      setProfiles(payload.profiles);
      setDuration(payload.duration);
      setStatus(payload.status);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [templateId, needHigh]);

  const { thumbnails: timelineThumbnails, intervalSec } = useMemo(
    () => selectThumbnailsForZoom(profiles, pxPerSec),
    [profiles, pxPerSec]
  );

  return {
    timelineThumbnails,
    profiles,
    loading: loading || (status === 'processing' && timelineThumbnails.length === 0),
    duration,
    status,
    sampleIntervalSec,
    activeIntervalSec: intervalSec,
  };
}

export type { TimelineThumbnail };
