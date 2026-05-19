import { useMemo, useState } from 'react'
import { Copy, Check } from 'lucide-react'

interface MarkdownRendererProps {
  content: string
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const html = useMemo(() => {
    let result = escapeHtml(content)

    result = result.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang">${lang || 'text'}</span></div><pre><code class="language-${lang || 'text'}">${escapeHtml(code.trimEnd())}</code></pre></div>`
    })

    result = result.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

    result = result.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
    result = result.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    result = result.replace(/\*(.*?)\*/g, '<em>$1</em>')
    result = result.replace(/~~(.*?)~~/g, '<del>$1</del>')

    result = result.replace(/^### (.*?)$/gm, '<h3>$1</h3>')
    result = result.replace(/^## (.*?)$/gm, '<h2>$1</h2>')
    result = result.replace(/^# (.*?)$/gm, '<h1>$1</h1>')

    result = result.replace(/^>- (.*?)$/gm, '<blockquote><li>$1</li></blockquote>')
    result = result.replace(/^> (.*?)$/gm, '<blockquote><p>$1</p></blockquote>')

    result = result.replace(/^(\d+)\. (.*?)$/gm, '<li value="$1">$2</li>')

    result = result.replace(/^- (.*?)(\n|$)/gm, '<li>$1</li>')
    result = result.replace(/^\* (.*?)(\n|$)/gm, '<li>$1</li>')

    result = result.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')

    const imgGlobalRegex = /!\[(.*?)\]\((.*?)\)/g
    result = result.replace(imgGlobalRegex, '<div class="markdown-image-wrapper"><img src="$2" alt="$1" class="markdown-image" loading="lazy" onerror="this.style.display=\'none\'" /></div>')

    const tableRegex = /\|(.+)\|\n\|[-| ]+\|\n((?:\|.+\|\n?)*)/g
    result = result.replace(tableRegex, (_, headerRow, bodyRows) => {
      const headers = headerRow.split('|').filter((h: string) => h.trim()).map((h: string) => `<th>${h.trim()}</th>`).join('')
      const rows = bodyRows.trim().split('\n').filter((r: string) => r.trim()).map((row: string) => {
        const cells = row.split('|').filter((c: string) => c.trim()).map((c: string) => `<td>${c.trim()}</td>`).join('')
        return `<tr>${cells}</tr>`
      }).join('')
      return `<div class="table-wrapper"><table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`
    })

    result = result.replace(/((?:<li[^>]*>[\s\S]*?<\/li>\s*)+)/gs, (match) => {
      if (match.includes('<ul>') || match.includes('<ol>')) return match
      if (match.includes('value=')) return `<ol>${match}</ol>`
      return `<ul>${match}</ul>`
    })

    const paragraphs = result.split(/\n\n+/)
    result = paragraphs.map((p) => {
      const trimmed = p.trim()
      if (!trimmed) return ''
      if (
        trimmed.startsWith('<h') || trimmed.startsWith('<pre') ||
        trimmed.startsWith('<ul') || trimmed.startsWith('<ol') ||
        trimmed.startsWith('<li') || trimmed.startsWith('<div') ||
        trimmed.startsWith('<blockquote') || trimmed.startsWith('<table')
      ) return trimmed
      return `<p>${trimmed.replace(/\n/g, '<br/>')}</p>`
    }).join('')

    return result
  }, [content])

  return (
    <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />
  )
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-lang">{language || 'code'}</span>
        <button className="code-copy-btn" onClick={handleCopy} title="Copy code">
          {copied ? <Check size={14} /> : <Copy size={14} />}
          <span>{copied ? 'Copied!' : 'Copy'}</span>
        </button>
      </div>
      <pre><code className={`language-${language || 'text'}`}>{code}</code></pre>
    </div>
  )
}
