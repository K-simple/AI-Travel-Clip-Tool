/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        editor: {
          bg: 'var(--editor-bg)',
          panel: 'var(--editor-panel)',
          'panel-2': 'var(--editor-panel-2)',
          elevated: 'var(--editor-elevated)',
          border: 'var(--editor-border)',
          'border-soft': 'var(--editor-border-soft)',
          text: 'var(--editor-text)',
          muted: 'var(--editor-muted)',
          subtle: 'var(--editor-subtle)',
          accent: 'rgb(245 197 24 / <alpha-value>)',
          'accent-hover': '#ffd84d',
          'accent-muted': 'var(--editor-accent-muted)',
          success: 'var(--editor-success)',
          danger: 'var(--editor-danger)',
        },
      },
      fontFamily: {
        sans: [
          'var(--font-sans)',
          'PingFang SC',
          'Microsoft YaHei',
          'Segoe UI',
          'system-ui',
          'sans-serif',
        ],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35)',
        glow: '0 0 0 1px rgba(245,197,24,0.15), 0 8px 32px rgba(245,197,24,0.08)',
      },
      borderRadius: {
        xl: '12px',
        '2xl': '16px',
      },
    },
  },
  plugins: [],
};
