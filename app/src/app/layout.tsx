import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mafer · Analyst workspace",
  description:
    "Explore saved GC-MS chromatograms, spectra, and library candidates.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
