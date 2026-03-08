// AGENT-CTX: Root layout required by Next.js 14 App Router.
// Minimal — no global CSS, no fonts, no providers needed for walking skeleton.
// Add providers here (e.g. React Query, theme) in future slices.

export const metadata = {
  title: "MATA — Drug Target Evidence",
  description: "Search PubMed evidence for drug targets",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
