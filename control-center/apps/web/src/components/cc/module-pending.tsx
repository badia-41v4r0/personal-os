import type { LucideIcon } from "lucide-react";
import { PageHeader } from "./shell";
import { Card, CardContent } from "@/components/ui/card";

/** Módulo aún sin datos. Dice lo que falta: nunca enseña cifras de ejemplo. */
export function ModulePending({ title, description, icon: Icon, missing }: { title: string; description: string; icon: LucideIcon; missing: string }) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <span className="grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground"><Icon className="size-5" /></span>
          <p className="font-medium">Todavía sin datos</p>
          <p className="max-w-md text-sm text-muted-foreground">{missing}</p>
        </CardContent>
      </Card>
    </>
  );
}
