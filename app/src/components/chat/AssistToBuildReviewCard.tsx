import { Check, GitBranch, RefreshCw } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import ReactMarkdown from 'react-markdown';

export interface AssistToBuildReviewSummary {
  stage: 'as_is' | 'to_be';
  title: string;
  summary_markdown: string;
  mermaid?: string | null;
  assumptions?: string[];
  risks?: string[];
  requirements?: string[];
}

export type AssistToBuildReviewResponse = 'approve_as_is' | 'approve_to_be_and_build' | 'request_changes';

function MermaidPreview({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const renderId = useId().replace(/:/g, '-');

  useEffect(() => {
    let active = true;
    if (!code.trim()) return;
    void import('mermaid').then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
      const rendered = await mermaid.render(`assist-to-build-${renderId}`, code);
      if (active) setSvg(rendered.svg);
    }).catch(() => active && setFailed(true));
    return () => { active = false; };
  }, [code, renderId]);

  if (failed) return <pre className="text-xs overflow-x-auto p-3 rounded bg-[var(--surface)]">{code}</pre>;
  if (!svg) return <div className="text-xs text-[var(--text-muted)]">Rendering process diagram…</div>;
  return <div className="mermaid-container diagram-scroll-container" dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function AssistToBuildReviewCard({ approvalId, summary, onRespond, resolvedResponse }: {
  approvalId: string;
  summary: AssistToBuildReviewSummary;
  onRespond: (approvalId: string, response: AssistToBuildReviewResponse, comment?: string) => void;
  resolvedResponse?: AssistToBuildReviewResponse;
}) {
  const isAsIs = summary.stage === 'as_is';
  const [comment, setComment] = useState('');
  return <section className="bg-[var(--primary)]/5 border-2 border-[var(--primary)]/30 rounded-lg p-4" aria-label={`${isAsIs ? 'AS-IS' : 'TO-BE'} process review`}>
    <div className="flex items-start gap-3 mb-3"><GitBranch className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" /><div><p className="text-xs font-semibold uppercase tracking-wide text-[var(--primary)]">{isAsIs ? 'AS-IS review' : 'TO-BE review'}</p><h4 className="font-semibold text-[var(--text)]">{summary.title}</h4></div></div>
    <div className="prose prose-sm max-w-none text-[var(--text)]/85 mb-3"><ReactMarkdown>{summary.summary_markdown}</ReactMarkdown></div>
    {summary.mermaid ? <div className="mb-3"><MermaidPreview code={summary.mermaid} /></div> : null}
    {([['Assumptions', summary.assumptions], ['Risks', summary.risks], ['Requirements', summary.requirements]] as const).map(([label, values]) => values?.length ? <div key={label} className="mb-2 text-sm"><span className="font-medium">{label}:</span><ul className="list-disc pl-5 text-[var(--text)]/75">{values.map((value) => <li key={value}>{value}</li>)}</ul></div> : null)}
    {resolvedResponse ? <p className="mt-4 text-sm text-[var(--text-muted)]">{resolvedResponse === 'request_changes' ? 'Changes requested — a revised checkpoint will follow.' : 'Checkpoint approved.'}</p> : <><label className="block mt-3 text-xs text-[var(--text-muted)]">Changes requested (optional)<textarea value={comment} onChange={(event) => setComment(event.target.value)} className="mt-1 w-full min-h-16 p-2 rounded border border-[var(--border)] bg-[var(--surface)] text-sm text-[var(--text)]" placeholder="Describe what should change" /></label><div className="flex gap-2 mt-4"><button onClick={() => onRespond(approvalId, isAsIs ? 'approve_as_is' : 'approve_to_be_and_build')} className="flex-1 px-3 py-2 bg-[var(--primary)]/20 hover:bg-[var(--primary)]/30 border border-[var(--primary)]/40 rounded-lg text-[var(--primary)] text-sm font-medium flex items-center justify-center gap-2"><Check className="w-4 h-4" />{isAsIs ? 'Approve AS-IS' : 'Approve TO-BE and start building'}</button><button onClick={() => onRespond(approvalId, 'request_changes', comment.trim() || undefined)} className="px-3 py-2 border border-[var(--border)] rounded-lg text-sm text-[var(--text)] hover:bg-[var(--surface-hover)] flex items-center gap-2"><RefreshCw className="w-4 h-4" />Request changes</button></div></>}
  </section>;
}
