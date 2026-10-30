"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Boxes,
  Database,
  GaugeCircle,
  LayoutDashboard,
  Play,
  Server,
} from "lucide-react";

import { cn } from "@/lib/utils";

const SECTIONS = [
  {
    label: "Workbench",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/datasets", label: "Datasets", icon: Database },
      { href: "/runs", label: "Runs", icon: Play },
    ],
  },
  {
    label: "Cluster",
    items: [
      { href: "/cluster", label: "HDFS and YARN", icon: Server },
      { href: "/storage", label: "HDFS browser", icon: Boxes },
    ],
  },
  {
    label: "Measurement",
    items: [{ href: "/benchmarks", label: "Benchmarks", icon: GaugeCircle }],
  },
] as const;

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-6" aria-label="Main">
      {SECTIONS.map((section) => (
        <div key={section.label}>
          <p className="px-2.5 pb-2 text-2xs font-medium text-muted-foreground/80">
            {section.label}
          </p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
