import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";
import { AppProvider } from "@/context/AppContext";

export const metadata: Metadata = {
  title: "Fantasy Baseball 2025",
  description:
    "Rankings, Team Builder, and Trade Analyzer powered by 2025 MLB z-scores",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-white antialiased">
        <AppProvider>
          <Nav />
          {children}
        </AppProvider>
      </body>
    </html>
  );
}
