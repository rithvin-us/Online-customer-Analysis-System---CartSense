import type { Metadata } from "next";
import Link from "next/link";
import { Inter, JetBrains_Mono } from "next/font/google";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ClusterStrip } from "@/components/workbench/cluster-strip";
import { Nav } from "@/components/workbench/nav";

import "./globals.css";

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CartScope",
  description:
    "Distributed retail intelligence: dataset ingestion into HDFS, native Hadoop " +
    "MapReduce analytics on YARN, and the counters and logs behind every figure.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} dark`}>
      <body className="min-h-screen bg-background">
        <TooltipProvider delayDuration={300}>
          <div className="flex min-h-screen">
            <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-surface-sunken px-3 py-4 lg:flex">
              <Link href="/" className="mb-6 flex items-baseline gap-2 px-2.5">
                <span className="text-base font-semibold tracking-tight">CartScope</span>
                <span className="text-2xs text-muted-foreground">workbench</span>
              </Link>
              <Nav />
              <div className="mt-auto px-2.5 pt-6 text-2xs leading-relaxed text-muted-foreground/70">
                Apache Hadoop 3.5.0 · HDFS · YARN · MapReduce
              </div>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
              <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background/95 px-5 py-2.5 backdrop-blur">
                <Link
                  href="/"
                  className="text-sm font-semibold tracking-tight lg:hidden"
                >
                  CartScope
                </Link>
                <ClusterStrip className="ml-auto" />
              </header>
              <main className="min-w-0 flex-1 px-5 py-5">{children}</main>
            </div>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
