import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const ALLOWED = new Set([
  'p', 'strong', 'em', 'code', 'ul', 'ol', 'li', 'blockquote', 'a', 'br', 'pre',
])

const COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="text-sm text-ink-secondary leading-relaxed whitespace-pre-wrap mb-1">{children}</p>,
  strong: ({ children }: { children?: React.ReactNode }) => <strong className="font-semibold text-ink-primary">{children}</strong>,
  em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
  code: ({ children }: { children?: React.ReactNode }) => <code className="text-xs font-mono bg-bg-tertiary px-1 py-0.5 rounded">{children}</code>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li className="text-sm text-ink-secondary">{children}</li>,
  blockquote: ({ children }: { children?: React.ReactNode }) => <blockquote className="border-l-2 border-border-color pl-3 my-1 text-ink-muted italic">{children}</blockquote>,
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    const safe = href?.startsWith('http://') || href?.startsWith('https://')
    return <a href={safe ? href : '#'} className="text-accent underline" target="_blank" rel="noopener noreferrer">{children}</a>
  },
  pre: ({ children }: { children?: React.ReactNode }) => <pre className="text-xs font-mono bg-bg-tertiary p-2 rounded my-1 overflow-x-auto">{children}</pre>,
  br: () => <br />,
}

export default function MarkdownText({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={ALLOWED}
      unwrapDisallowed
      components={COMPONENTS}
    >
      {children}
    </ReactMarkdown>
  )
}
