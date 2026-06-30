import { useEffect, useState } from 'react';
import { fetchTemplateWaveform } from '@/lib/waveform';

export function useTimelineWaveform(templateId?: string | null) {
  const [templateWaveform, setTemplateWaveform] = useState<number[]>([]);

  useEffect(() => {
    if (!templateId) {
      setTemplateWaveform([]);
      return;
    }
    void fetchTemplateWaveform(templateId, 400).then(setTemplateWaveform);
  }, [templateId]);

  return templateWaveform;
}
