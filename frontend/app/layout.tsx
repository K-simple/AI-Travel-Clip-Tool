import './globals.css';

export const metadata = {
  title: 'AI 旅游混剪',
  description: '模板驱动的 AI 旅游混剪工具',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
