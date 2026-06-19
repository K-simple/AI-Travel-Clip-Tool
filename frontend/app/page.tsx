import Link from 'next/link';

const FEATURES = [
  {
    title: '模板智能切分',
    desc: '上传参考视频，自动识别镜头槽位与字幕节奏',
  },
  {
    title: '素材一键匹配',
    desc: 'AI 按场景标签与画面相似度匹配旅行素材',
  },
  {
    title: '剪映草稿导出',
    desc: '导出可替换模板草稿，在剪映中逐段替换成片',
  },
];

export default function HomePage() {
  return (
    <main className="relative flex min-h-dvh flex-col overflow-hidden bg-editor-bg">
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden
        style={{
          background:
            'radial-gradient(ellipse 80% 50% at 50% -20%, rgba(245,197,24,0.12), transparent 60%), radial-gradient(ellipse 60% 40% at 100% 100%, rgba(59,90,128,0.15), transparent 50%)',
        }}
      />

      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-editor-accent-muted text-lg font-bold text-editor-accent">
            ✦
          </span>
          <span className="text-sm font-semibold text-editor-text">AI 旅游混剪</span>
        </div>
        <Link href="/editor" className="ui-btn-ghost hidden sm:inline-flex">
          直接进入编辑器 →
        </Link>
      </header>

      <section className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 pb-16 pt-4 text-center sm:px-10">
        <p className="mb-4 inline-flex items-center rounded-full border border-editor-border bg-editor-panel/80 px-3 py-1 text-xs text-editor-muted backdrop-blur-sm">
          模板驱动 · 智能匹配 · 剪映协作
        </p>
        <h1 className="max-w-2xl text-3xl font-bold leading-tight tracking-tight text-white sm:text-5xl">
          把旅行素材
          <span className="text-editor-accent"> 快速剪成 </span>
          爆款竖版视频
        </h1>
        <p className="mt-5 max-w-lg text-sm leading-relaxed text-editor-muted sm:text-base">
          上传模板视频，自动切分镜头，智能匹配旅行素材，一键导出竖版成片或剪映可替换草稿。
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <Link href="/editor" className="ui-btn-primary px-8 py-3 text-sm">
            开始创作
          </Link>
          <span className="text-xs text-editor-subtle">无需安装，浏览器即用</span>
        </div>

        <div className="mt-16 grid w-full max-w-3xl gap-4 sm:grid-cols-3">
          {FEATURES.map((item) => (
            <div
              key={item.title}
              className="ui-card rounded-2xl p-5 text-left shadow-panel backdrop-blur-sm"
            >
              <h3 className="text-sm font-semibold text-editor-text">{item.title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-editor-muted">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
