/**
 * Typed constructor for a panel's message table.
 *
 * Every panel that gets localised ships one module of this shape, and the
 * compiler is the first quality gate: because `K` is inferred from the union of
 * all three tables, a key present in one locale and missing in another is a type
 * error, not a silent runtime fallback to Chinese. Extra keys are rejected the
 * same way, so a stale translation cannot linger after a label is removed.
 *
 * `scripts/i18n_inventory.py` reports the same invariants textually (for CI jobs
 * that never load the bundler) and `i18n/coverage.test.ts` re-checks them at
 * runtime, including placeholder parity.
 */
export type PanelMessageTables<K extends string = string> = {
  'zh-CN': Record<K, string>
  'en-US': Record<K, string>
  'ja-JP': Record<K, string>
}

export const definePanelMessages = <K extends string>(
  tables: PanelMessageTables<K>,
): PanelMessageTables<K> => tables
