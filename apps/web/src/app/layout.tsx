import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "Convo / Your files. A conversation.",
  description:
    "Chat with your files, right from your terminal. Install Convo, open a directory, and get answers with supporting source quotations.",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = { themeColor: "#000000" };

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="bg-surface font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
