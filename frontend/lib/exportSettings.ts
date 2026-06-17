import type { TrackControls, TrackKey } from '@/lib/trackControls';
import { hasActiveSolo, TRACK_KEYS } from '@/lib/trackControls';

function trackActive(controls: Record<TrackKey, TrackControls>, key: TrackKey): boolean {
  const ctrl = controls[key];
  if (!ctrl.visible) return false;
  if (hasActiveSolo(controls)) return ctrl.solo;
  return true;
}

export type ExportMixOptions = {
  trackControls: Record<TrackKey, TrackControls>;
  templateMusicEnabled: boolean;
  useAssetAudio: boolean;
  assetAudioVolume?: number;
  templateAudioVolume?: number;
  addSubtitles: boolean;
};

export function buildExportPayload(options: ExportMixOptions) {
  const {
    trackControls,
    templateMusicEnabled,
    useAssetAudio,
    assetAudioVolume = 0.8,
    templateAudioVolume = 1.0,
    addSubtitles,
  } = options;

  let templateVol = templateMusicEnabled ? templateAudioVolume : 0;
  if (!trackActive(trackControls, 'audio') || trackControls.audio.muted) {
    templateVol = 0;
  }

  let assetAudio = useAssetAudio;
  if (
    !trackActive(trackControls, 'audioVoice') ||
    trackControls.audioVoice.muted ||
    !trackActive(trackControls, 'video') ||
    trackControls.video.muted
  ) {
    assetAudio = false;
  }

  let burnSubtitles = addSubtitles;
  if (!trackActive(trackControls, 'subtitle') || trackControls.subtitle.muted) {
    burnSubtitles = false;
  }

  const overlayActive =
    trackActive(trackControls, 'overlay') && !trackControls.overlay.muted;
  const stickerActive =
    trackActive(trackControls, 'sticker') && !trackControls.sticker.muted;

  return {
    add_subtitles: burnSubtitles,
    use_slot_subtitles: true,
    use_asset_audio: assetAudio,
    template_audio_volume: templateVol,
    asset_audio_volume: assetAudioVolume,
    track_controls: trackControls,
    include_overlay: overlayActive || stickerActive,
    include_video2: trackActive(trackControls, 'video2') && !trackControls.video2.muted,
  };
}
