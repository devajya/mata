// AGENT-CTX: Root layout required by Next.js 14 App Router.
// Minimal — no global CSS, no fonts, no providers needed for walking skeleton.
// Add providers here (e.g. React Query, theme) in future slices.

// AGENT-CTX: @xyflow/react CSS must be imported at the layout level (not inside
// EvidenceGraph.tsx) because Next.js App Router only allows CSS imports in
// Server Components or layout files, not in Client Components ("use client").
import "@xyflow/react/dist/style.css";

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
