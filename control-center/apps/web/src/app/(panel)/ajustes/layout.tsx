"use client";

import { AjustesNav } from "@/components/cc/subnav";

export default function AjustesLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="lg:flex lg:gap-8">
      <AjustesNav />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
