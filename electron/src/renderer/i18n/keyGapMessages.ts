import { definePanelMessages } from './definePanelMessages'

/**
 * Keys that a component already renders through `t()` but that no locale table
 * defined yet, so the raw key (for example `settings.llm.apiKeyNotRequired`)
 * leaked into the UI for every language.
 *
 * Kept as a module instead of an extra line inside the `index.ts` literals so
 * the key cannot silently drift out of one locale again: `definePanelMessages`
 * rejects a table that misses it, and the spread below is identical per locale.
 */
export const keyGapMessages = definePanelMessages({
  'zh-CN': {
    'settings.llm.apiKeyNotRequired': '当前提供商不需要 API Key',
  },
  'en-US': {
    'settings.llm.apiKeyNotRequired': 'This provider does not need an API key',
  },
  'ja-JP': {
    'settings.llm.apiKeyNotRequired': 'このプロバイダーは API キーが不要です',
  },
})
