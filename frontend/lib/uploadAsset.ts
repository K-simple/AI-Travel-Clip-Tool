import { apiUrl } from '@/lib/api';

export type UploadProgress = {
  loaded: number;
  total: number;
  percent: number;
};

export function uploadFileWithProgress(
  path: string,
  file: File,
  onProgress?: (progress: UploadProgress) => void
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append('file', file);

    xhr.upload.onprogress = (event) => {
      if (!onProgress) return;
      const total = event.lengthComputable ? event.total : file.size;
      const loaded = event.loaded;
      const percent = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
      onProgress({ loaded, total, percent });
    };

    xhr.onerror = () => reject(new Error('网络错误，上传失败'));
    xhr.onabort = () => reject(new Error('上传已取消'));

    xhr.onload = () => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(xhr.responseText || '{}') as Record<string, unknown>;
      } catch {
        reject(new Error('服务器响应无效'));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
        return;
      }
      const detail = data.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => (typeof d === 'object' && d && 'msg' in d ? String(d.msg) : String(d))).join('; ')
            : `上传失败 (${xhr.status})`;
      reject(new Error(message));
    };

    xhr.open('POST', apiUrl(path));
    const apiKey = process.env.NEXT_PUBLIC_API_KEY;
    if (apiKey) {
      xhr.setRequestHeader('X-API-Key', apiKey);
    }
    xhr.send(formData);
  });
}

export function uploadAssetWithProgress(
  file: File,
  onProgress?: (progress: UploadProgress) => void
): Promise<Record<string, unknown>> {
  return uploadFileWithProgress('/api/assets/upload', file, onProgress);
}

export function uploadTemplateWithProgress(
  file: File,
  onProgress?: (progress: UploadProgress) => void
): Promise<Record<string, unknown>> {
  return uploadFileWithProgress('/api/template/upload', file, onProgress);
}
