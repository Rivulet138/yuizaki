/** 简单 Markdown → HTML 渲染（仅支持聊天场景常用语法） */
const escapeAttribute = (value: string): string => value
  .replace(/&/g, '&amp;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const decodeUrlEntities = (value: string): string => value
  .replace(/&amp;/g, '&')
  .replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'")

const safeLinkHref = (rawUrl: string): string | null => {
  const trimmed = decodeUrlEntities(rawUrl).trim()
  if (/[\s"'<>]/.test(trimmed)) return null
  try {
    const parsed = new URL(trimmed)
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? escapeAttribute(parsed.href) : null
  } catch {
    return null
  }
}

export function renderMarkdown(text: string): string {
  if (!text) return ''

  let html = text
    // 转义 HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 代码块 ```
  html = html.replace(/```(?:\w*)\n([\s\S]*?)```/g, (_m, code: string) => {
    return `<pre class="md-code"><code>${code.trim()}</code></pre>`
  })

  // 行内代码 `code`
  html = html.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>')

  // 粗体 **text**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // 斜体 *text*
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // 链接 [text](url)：只允许明确的 http/https/mailto，避免 v-html 注入危险协议或属性。
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match: string, label: string, rawUrl: string) => {
    if (!match) return label
    const href = safeLinkHref(rawUrl)
    return href ? `<a href="${href}" target="_blank" rel="noopener noreferrer" class="md-link">${label}</a>` : label
  })

  // 无序列表
  html = html.replace(/^[-*]\s+(.+)$/gm, '<li class="md-li">$1</li>')

  // 换行
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = `<p class="md-p">${html}</p>`

  return html
}
