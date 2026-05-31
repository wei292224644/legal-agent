import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const ALLOWED = new Set([
  'p', 'strong', 'em', 'code', 'ul', 'ol', 'li', 'blockquote', 'a', 'br', 'pre',
])

export default function MarkdownText({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={ALLOWED}
      unwrapDisallowed
      components={{
        p: ({ children }) => <p className="text-sm text-ink-secondary leading-relaxed whitespace-pre-wrap mb-1">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-ink-primary">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        code: ({ children }) => <code className="text-xs font-mono bg-bg-tertiary px-1 py-0.5 rounded">{children}</code>,
        ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
        li: ({ children }) => <li className="text-sm text-ink-secondary">{children}</li>,
        blockquote: ({ children }) => <blockquote className="border-l-2 border-border-color pl-3 my-1 text-ink-muted italic">{children}</blockquote>,
        a: ({ href, children }) => <a href={href} className="text-accent underline" target="_blank" rel="noopener noreferrer">{children}</a>,
        pre: ({ children }) => <pre className="text-xs font-mono bg-bg-tertiary p-2 rounded my-1 overflow-x-auto">{children}</pre>,
        br: () => <br />,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
