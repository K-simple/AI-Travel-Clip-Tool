import type { PreviewQualityId } from '@/lib/previewSettings';

/** 手机 / 平板浏览器 */
export function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Android|iPhone|iPad|iPod|Mobile|webOS/i.test(navigator.userAgent);
}

/** 千元机或 ~3000 元档 PC 浏览器（4 核 / ≤4GB 内存） */
export function isLowEndClient(): boolean {
  if (typeof navigator === 'undefined') return false;
  if (isMobileDevice()) return true;
  const cores = navigator.hardwareConcurrency ?? 8;
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (cores <= 4) return true;
  if (mem !== undefined && mem <= 4) return true;
  return false;
}

/** 低配默认 480p 预览，减少解码与带宽 */
export function defaultPreviewQuality(): PreviewQualityId {
  return isLowEndClient() ? 'low' : 'smooth';
}

/** 模板状态轮询间隔（低配降低请求频率） */
export function templateStatusPollMs(): number {
  return isLowEndClient() ? 2500 : 1500;
}
