export type Health = { ok: boolean; backend: string; database: string; host_agent: string; transcripts: string };

export type Metrics = {
  ts: string;
  cpu: { pct: number; per_core: number[]; count: number; load: number[] };
  memory: { total: number; used: number; available: number; pct: number };
  swap: { total: number; used: number; pct: number };
  temperatures: Record<string, number>;
  gpu: { name: string; util_pct: number; vram_used_mb: number; vram_total_mb: number; temp_c: number }[];
  disks: { mount: string; fs: string; total: number; used: number; free: number; pct: number }[];
  net: { bytes_sent: number; bytes_recv: number };
  uptime_s: number;
  top_processes: { pid: number; name: string; rss: number; user: string }[];
};

export type Unit = {
  Id: string; Description: string; ActiveState: string; SubState: string; Result?: string;
  NRestarts?: string; UnitFileState?: string; scope: "user" | "system";
  ActiveEnterTimestamp?: string; NextElapseUSecRealtime?: string; LastTriggerUSec?: string;
};

export type Container = { ID: string; Names: string; Image: string; State: string; Status: string; RunningFor: string };

export type TranscriptItem = {
  uuid: string; ts: string; kind: "message" | "tool_call" | "tool_result" | "thinking" | "notice" | "turn_end";
  role: string; channel: string; text: string; tool: string; tool_input: Record<string, string>;
  is_error: boolean; meta: Record<string, string>;
};
