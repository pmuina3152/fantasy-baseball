import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fantasy Baseball Rankings 2025",
  description:
    "Top 100 fantasy baseball hitter and pitcher rankings by z-score for the 2025 MLB season",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-white antialiased">
        {children}
      </body>
    </html>
  );
}
