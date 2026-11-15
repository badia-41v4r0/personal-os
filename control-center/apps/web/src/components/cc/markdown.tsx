"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown de Obsidian a HTML seguro (react-markdown no interpreta HTML crudo).
 * - [[nota|alias]] → enlace interno (onWiki); ![[imagen.png]] → imagen servida por /memory/raw.
 * - Frontmatter YAML: se quita del cuerpo y se devuelve aparte.
 */
export function splitFrontmatter(src: string): { meta: [string, string][]; body: string } {
  const m = src.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!m) return { meta: [], body: src };
  const meta = m[1]
    .split("\n")
    .map((l) => l.match(/^([\w-]+):\s*(.*)$/))
    .filter(Boolean)
    .map((x) => [x![1], x![2]] as [string, string]);
  return { meta, body: src.slice(m[0].length) };
}

function preprocess(md: string): string {
  return md
    .replace(/!\[\[([^\]|]+?\.(?:png|jpe?g|gif|webp|svg))(?:\|[^\]]*)?\]\]/gi, (_, f) => `![${f}](wikiimg:${encodeURIComponent(f)})`)
    .replace(/\[\[([^\]|#]+)(#[^\]|]*)?(?:\\?\|([^\]]+))?\]\]/g, (_, target, _h, alias) => `[${alias ?? target.split("/").pop()}](wiki:${encodeURIComponent(target)})`);
}

export function Markdown({ source, onWiki, imageSrc }: { source: string; onWiki: (target: string) => void; imageSrc: (name: string) => string }) {
  return (
    <div className="prose-cc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => url}
        components={{
          a: ({ href = "", children }) => {
            if (href.startsWith("wiki:")) {
              const t = decodeURIComponent(href.slice(5));
              return (
                <a href="#" className="text-primary hover:underline" onClick={(e) => { e.preventDefault(); onWiki(t); }}>
                  {children}
                </a>
              );
            }
            const safe = /^(https?:|mailto:)/i.test(href);
            return safe ? <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-primary hover:underline">{children}</a> : <span>{children}</span>;
          },
          img: ({ src = "", alt }) => {
            const s = String(src);
            if (s.startsWith("wikiimg:")) {
              // eslint-disable-next-line @next/next/no-img-element
              return <img src={imageSrc(decodeURIComponent(s.slice(8)))} alt={alt ?? ""} className="max-h-96 rounded-lg" />;
            }
            return <span className="text-xs text-muted-foreground">[imagen externa: {alt || "sin título"}]</span>;
          },
          input: ({ checked }) => <input type="checkbox" checked={!!checked} readOnly className="mr-1.5 align-middle accent-[var(--primary)]" />,
        }}
      >
        {preprocess(source)}
      </ReactMarkdown>
    </div>
  );
}
