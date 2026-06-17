import Link from 'next/link';
import './globals.css';

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-[#141414] px-6 text-center">
      <h1 className="text-3xl font-bold text-white">AI 旅游混剪</h1>
      <p className="mt-3 max-w-md text-sm text-[#8b8b8b]">
        上传模板视频，自动切分镜头，智能匹配旅行素材，一键导出竖版成片。
      </p>
      <Link
        href="/editor"
        className="mt-8 rounded-lg bg-[#face15] px-8 py-3 text-sm font-semibold text-black hover:bg-[#ffe066]"
      >
        进入编辑器
      </Link>
    </main>
  );
}
