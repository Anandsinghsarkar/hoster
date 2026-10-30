export const metadata = {
  title: 'Cyber Host',
  description: 'Telegram bot hosting dashboard'
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, minHeight: '100vh' }}>{children}</body>
    </html>
  );
}
