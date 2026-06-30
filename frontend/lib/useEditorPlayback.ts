import { useCallback, useEffect, useRef, useState } from 'react';
import { snapToFrame } from '@/lib/timelineLayout';

export function useEditorPlayback(totalDuration: number) {
  const [playheadTime, setPlayheadTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const playRafRef = useRef<number | null>(null);
  const playStartRef = useRef({ wall: 0, time: 0 });
  const playheadRef = useRef(0);

  useEffect(() => {
    playheadRef.current = playheadTime;
  }, [playheadTime]);

  const handlePlayheadStep = useCallback(
    (deltaSec: number) => {
      setIsPlaying(false);
      setPlayheadTime((t) => snapToFrame(Math.max(0, Math.min(totalDuration, t + deltaSec))));
    },
    [totalDuration]
  );

  const handleTogglePlay = useCallback(() => {
    setIsPlaying((playing) => {
      if (!playing) {
        playStartRef.current = { wall: performance.now(), time: playheadRef.current };
      }
      return !playing;
    });
  }, []);

  const handlePlayheadChange = useCallback(
    (time: number) => {
      const snapped = snapToFrame(time);
      setPlayheadTime(snapped);
      playheadRef.current = snapped;
      if (snapped >= totalDuration - 1 / 30) {
        setIsPlaying(false);
      }
    },
    [totalDuration]
  );

  const handleScrubStart = useCallback(() => {
    setIsPlaying(false);
  }, []);

  useEffect(() => {
    if (isPlaying) {
      if (playRafRef.current != null) {
        cancelAnimationFrame(playRafRef.current);
        playRafRef.current = null;
      }
      return;
    }
    if (playRafRef.current != null) {
      cancelAnimationFrame(playRafRef.current);
      playRafRef.current = null;
    }
  }, [isPlaying]);

  return {
    playheadTime,
    setPlayheadTime,
    isPlaying,
    setIsPlaying,
    playheadRef,
    playStartRef,
    playRafRef,
    handlePlayheadStep,
    handleTogglePlay,
    handlePlayheadChange,
    handleScrubStart,
  };
}
