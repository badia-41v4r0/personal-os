"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { post, setCsrf } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/cc/logo";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ csrf_token: string }>("/auth/login", { username, password });
      setCsrf(r.csrf_token);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo entrar");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-xl border border-border bg-card p-6 shadow-2xl shadow-black/30">
        <div className="space-y-1">
          <div className="mb-4">
            <Logo className="size-10" />
          </div>
          <h1 className="text-lg font-semibold tracking-tight">Personal OS</h1>
          <p className="text-sm text-muted-foreground">Acceso privado.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="u">Usuario</Label>
          <Input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="p">Contraseña</Label>
          <Input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" size="lg" disabled={busy}>
          {busy ? "Entrando…" : "Entrar"}
        </Button>
      </form>
    </main>
  );
}
