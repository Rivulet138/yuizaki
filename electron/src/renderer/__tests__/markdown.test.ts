import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../utils/markdown'

describe('renderMarkdown', () => {
  it('allows safe external links with opener isolation', () => {
    expect(renderMarkdown('[官网](https://example.com/docs?a=1&b=2)')).toContain(
      '<a href="https://example.com/docs?a=1&amp;b=2" target="_blank" rel="noopener noreferrer" class="md-link">官网</a>',
    )
  })

  it('drops unsafe link schemes before v-html rendering', () => {
    const html = renderMarkdown('[点我](javascript:alert(1))')

    expect(html).not.toContain('<a ')
    expect(html).not.toContain('javascript:')
    expect(html).toContain('点我')
  })

  it('does not allow link attribute injection', () => {
    const html = renderMarkdown('[x](https://example.com/&quot; onclick=&quot;alert(1))')

    expect(html).not.toContain('<a ')
    expect(html).not.toContain('onclick=')
    expect(html).toContain('x')
  })
})
