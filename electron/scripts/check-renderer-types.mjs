#!/usr/bin/env node
/**
 * Renderer type-check gate.
 *
 * The renderer was never part of a TypeScript program, so enabling `vue-tsc`
 * surfaces a large backlog of existing errors at once. This gate keeps the
 * backlog visible and ratchets it down: a run fails only when an error that is
 * not in the committed baseline appears. Fixing errors is always allowed and
 * `--update` records the improvement.
 */

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const baselinePath = path.join(electronRoot, 'renderer-types-baseline.json')
const projectPath = path.join(electronRoot, 'tsconfig.renderer.json')
const vueTscEntry = path.join(electronRoot, 'node_modules', 'vue-tsc', 'bin', 'vue-tsc.js')

const updateBaseline = process.argv.includes('--update')

const ERROR_LINE = /^(?<file>[^\s(][^(]*)\((?<line>\d+),(?<column>\d+)\): error (?<code>TS\d+): (?<message>.*)$/

const normalizeMessage = (message) => message.replace(/\s+/g, ' ').trim()

const parseErrors = (output) => {
  const errors = new Map()
  for (const rawLine of output.split(/\r?\n/)) {
    const match = ERROR_LINE.exec(rawLine)
    if (!match?.groups) continue
    const file = match.groups.file.replaceAll('\\', '/').replace(/^\.\//, '')
    const key = `${file}:${match.groups.code}:${normalizeMessage(match.groups.message)}`
    errors.set(key, (errors.get(key) ?? 0) + 1)
  }
  return errors
}

const readBaseline = () => {
  if (!fs.existsSync(baselinePath)) return null
  try {
    const parsed = JSON.parse(fs.readFileSync(baselinePath, 'utf8'))
    if (!Array.isArray(parsed?.errors)) throw new Error('baseline is missing an errors array')
    const fileCounts = parsed?.fileCounts && typeof parsed.fileCounts === 'object' ? parsed.fileCounts : {}
    return {
      errors: new Set(parsed.errors.map(String)),
      fileCounts: new Map(Object.entries(fileCounts).map(([file, count]) => [file, Number(count) || 0])),
    }
  } catch (error) {
    console.error(`[ERROR] Unreadable renderer type baseline: ${error.message}`)
    process.exit(2)
  }
}

const fileCountsOf = (errors) => {
  const counts = new Map()
  for (const [key, occurrences] of errors) {
    const file = key.slice(0, key.indexOf(':'))
    counts.set(file, (counts.get(file) ?? 0) + occurrences)
  }
  return counts
}

const writeBaseline = (errors) => {
  const payload = {
    version: 2,
    generatedAt: new Date().toISOString(),
    note: 'Known vue-tsc errors in the renderer program. Regenerate with: node scripts/check-renderer-types.mjs --update',
    total: [...errors.values()].reduce((sum, count) => sum + count, 0),
    errors: [...errors.keys()].sort(),
    fileCounts: Object.fromEntries([...fileCountsOf(errors)].sort(([left], [right]) => left.localeCompare(right))),
  }
  fs.writeFileSync(baselinePath, `${JSON.stringify(payload, null, 2)}\n`)
}

if (!fs.existsSync(vueTscEntry)) {
  console.error('[ERROR] vue-tsc is not installed; run npm ci in electron/ first.')
  process.exit(2)
}

const result = spawnSync(process.execPath, [vueTscEntry, '--noEmit', '-p', projectPath], {
  cwd: electronRoot,
  encoding: 'utf8',
  shell: false,
  maxBuffer: 32 * 1024 * 1024,
})
if (result.error) {
  console.error(`[ERROR] Failed to run vue-tsc: ${result.error.message}`)
  process.exit(2)
}

const output = `${result.stdout ?? ''}${result.stderr ?? ''}`
const errors = parseErrors(output)
const baseline = readBaseline()

if (errors.size === 0 && result.status !== 0 && baseline === null) {
  console.error('[ERROR] vue-tsc failed without a parsable diagnostic:')
  console.error(output.trim().slice(0, 4000))
  process.exit(2)
}

if (updateBaseline) {
  if (result.status !== 0 && errors.size === 0) {
    console.error('[ERROR] Refusing to update the renderer baseline after an unparsed vue-tsc failure.')
    console.error(output.trim().slice(0, 4000))
    process.exit(2)
  }
  writeBaseline(errors)
  console.log(`Renderer type baseline written: ${errors.size} distinct errors across ${path.basename(projectPath)}`)
  process.exit(0)
}

if (baseline === null) {
  console.error('[ERROR] Missing renderer-types-baseline.json; create it with --update.')
  process.exit(2)
}

const regressions = [...errors.keys()].filter((key) => !baseline.errors.has(key))
const resolved = [...baseline.errors].filter((key) => !errors.has(key))
const currentFileCounts = fileCountsOf(errors)
const totalCount = [...errors.values()].reduce((sum, count) => sum + count, 0)
const grownFiles = [...currentFileCounts]
  .filter(([file, count]) => count > (baseline.fileCounts.get(file) ?? 0))
  .map(([file, count]) => ({ file, current: count, baseline: baseline.fileCounts.get(file) ?? 0 }))

if (resolved.length > 0) {
  console.log(`Renderer types: ${resolved.length} baselined error message(s) no longer reported.`)
}
console.log(`Renderer types: ${totalCount} known error(s) in ${currentFileCounts.size} file(s); new message(s) ${regressions.length}; files over baseline ${grownFiles.length}.`)

if (regressions.length > 0 || grownFiles.length > 0) {
  if (regressions.length > 0) {
    console.error('\n[ERROR] New renderer type errors are not allowed:')
    for (const key of regressions.slice(0, 40)) console.error(`  - ${key}`)
    if (regressions.length > 40) console.error(`  ... and ${regressions.length - 40} more`)
  }
  if (grownFiles.length > 0) {
    console.error('\n[ERROR] Files with more type errors than the baseline:')
    for (const entry of grownFiles.slice(0, 40)) {
      console.error(`  - ${entry.file}: ${entry.current} (baseline ${entry.baseline})`)
    }
  }
  console.error('\nFix the error, or rerun with --update only when the new error is an accepted, tracked baseline item.')
  process.exit(1)
}

if (result.status !== 0 && errors.size === 0) {
  console.error('[ERROR] vue-tsc failed without a parsable diagnostic:')
  console.error(output.trim().slice(0, 4000))
  process.exit(2)
}

console.log('Renderer type gate passed: no new errors beyond the recorded baseline.')
