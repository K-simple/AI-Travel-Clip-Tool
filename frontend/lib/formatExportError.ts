const ERROR_PATTERNS: Array<{ test: RegExp; message: string }> = [
  {
    test: /模板仍在后台处理|processing/i,
    message: '模板还在分析中，请等进度条走完后再导出',
  },
  {
    test: /模板视频文件不存在|模板不存在/i,
    message: '找不到模板视频文件，请重新上传模板',
  },
  {
    test: /项目不存在/i,
    message: '项目不存在或已被删除，请重新导入模板创建项目',
  },
  {
    test: /nvenc|encoder|codec|编码/i,
    message: '视频编码失败，可能是显卡驱动或 ffmpeg 配置问题，请稍后重试或联系管理员',
  },
  {
    test: /not found/i,
    message: '后端接口未就绪，请重启 backend 服务后重试',
  },
  {
    test: /timed out|timeout|超时/i,
    message: '导出耗时过长已超时，可尝试减少槽位数量或降低分辨率后重试',
  },
  {
    test: /disk|space|no space|磁盘/i,
    message: '磁盘空间不足，请清理 storage 目录后重试',
  },
  {
    test: /permission|denied|EPERM/i,
    message: '没有写入权限，请检查 storage/exports 目录权限',
  },
  {
    test: /ffmpeg|filter_complex/i,
    message: '视频合成失败，可能是某个素材文件损坏或路径无效',
  },
  {
    test: /无法连接剪映小助手|请先启动 CapCut Mate|Connection refused|ECONNREFUSED/i,
    message:
      '剪映小助手未连接，请先运行 scripts/start-capcut-mate.ps1 启动服务（默认 http://127.0.0.1:30000）',
  },
  {
    test: /无法访问素材 URL|CapCut Mate 无法访问素材/i,
    message:
      '剪映小助手无法下载素材，请确认 backend 在 http://127.0.0.1:8000 运行，且 backend/.env 中 PUBLIC_MEDIA_BASE_URL=http://127.0.0.1:8000',
  },
  {
    test: /video_url must start with http|参数校验失败.*video_infos|素材 URL 格式无效|素材 URL 为空/i,
    message:
      '素材 URL 格式无效，请刷新页面后重试；若仍失败，确认 backend/.env 已设置 PUBLIC_MEDIA_BASE_URL=http://127.0.0.1:8000 并重启 backend',
  },
  {
    test: /草稿创建失败|未返回 draft_url|DRAFT_CREATE/i,
    message: '剪映草稿创建失败，请重启 CapCut Mate 后重试（查看 capcut-mate/logs 日志）',
  },
];

export function formatExportError(raw: unknown): string {
  const text =
    typeof raw === 'string'
      ? raw
      : raw instanceof Error
        ? raw.message
        : typeof raw === 'object' && raw && 'detail' in raw
          ? String((raw as { detail: unknown }).detail)
          : '导出失败，请重试';

  const trimmed = text.trim();
  if (!trimmed) return '导出失败，请重试';

  for (const { test, message } of ERROR_PATTERNS) {
    if (test.test(trimmed)) return message;
  }

  if (trimmed.startsWith('视频导出失败:') || trimmed.startsWith('Export failed')) {
    return '视频合成出错，请检查所有槽位是否已匹配有效素材后重试';
  }

  return trimmed.length > 120 ? `${trimmed.slice(0, 117)}…` : trimmed;
}
