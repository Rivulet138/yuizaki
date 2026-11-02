import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const root = fileURLToPath(new URL('../', import.meta.url))
const consumer = createRequire(new URL('../package.json', import.meta.url))
const builder = () => createRequire(createRequire(consumer.resolve('electron-builder')).resolve('app-builder-lib'))
type Consumer = ReturnType<typeof createRequire>

function metadata(requireFrom: Consumer, name: string) {
  let directory = path.dirname(requireFrom.resolve(name))
  while (true) {
    const manifest = path.join(directory, 'package.json')
    if (fs.existsSync(manifest)) {
      const data = JSON.parse(fs.readFileSync(manifest, 'utf8'))
      if (data.name === name) return { ...data, manifest }
    }
    const parent = path.dirname(directory)
    if (parent === directory) throw new Error('Missing metadata: ' + name)
    directory = parent
  }
}

function minimatches() {
  const manifests: string[] = []
  const seen = new Set<string>()
  function visit(directory: string) {
    const real = fs.realpathSync(directory)
    if (seen.has(real)) return
    seen.add(real)
    for (const name of fs.readdirSync(directory)) {
      if (name.startsWith('.')) continue
      const entry = path.join(directory, name)
      if (!fs.statSync(entry).isDirectory()) continue
      const packages = name.startsWith('@') ? fs.readdirSync(entry).map(n => path.join(entry, n)) : [entry]
      for (const pkg of packages) {
        if (path.basename(pkg) === 'minimatch') manifests.push(path.join(pkg, 'package.json'))
        const nested = path.join(pkg, 'node_modules')
        if (fs.existsSync(nested)) visit(nested)
      }
    }
  }
  visit(path.join(root, 'node_modules'))
  expect(manifests.length).toBeGreaterThan(0)
  return manifests.sort()
}

async function temporary(run: (directory: string) => unknown | Promise<unknown>) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'dependency security '))
  try { await run(directory) } finally { fs.rmSync(directory, { recursive: true, force: true }) }
}

// Isolate temp's process-global tracking and bound adversarial pattern expansion.
function child(source: string, entries: Record<string, string> | string[], cwd: string) {
  const prelude = "const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');const {createRequire}=require('node:module');const entries=JSON.parse(process.argv[1]);\n"
  const script = prelude + '(async()=>{\n' + source + '\n})().catch(e=>{console.error(e);process.exitCode=1})'
  const result = spawnSync(process.execPath, ['--input-type=commonjs', '--eval', script, JSON.stringify(entries)], {
    cwd, encoding: 'utf8', timeout: 10_000, killSignal: 'SIGKILL', maxBuffer: 1024 * 1024,
  })
  const message = [result.error?.message, result.signal, result.stderr, result.stdout].filter(Boolean).join('\n')
  expect(result.error, message).toBeUndefined()
  expect(result.signal, message).toBeNull()
  expect(result.status, message).toBe(0)
  expect(result.stdout, message).toContain('passed')
}

function legacyTemp() {
  const squirrel = createRequire(builder().resolve('electron-builder-squirrel-windows'))
  const installer = createRequire(squirrel.resolve('electron-winstaller'))
  return installer.resolve('temp')
}

describe('Dependency security real consumers', () => {
  it('requires every installed minimatch >=11.0.1', () => {
    const semver = builder()('semver')
    for (const manifest of minimatches()) {
      const data = JSON.parse(fs.readFileSync(manifest, 'utf8'))
      expect(data.name, manifest).toBe('minimatch')
      expect(semver.gte(data.version, '11.0.1'), manifest + ': ' + data.version).toBe(true)
    }
  })

  it('creates, reads and extracts builder-resolved asar4 using glob >=14.0.3', async () => {
    const requireFrom = builder()
    expect(metadata(requireFrom, '@electron/asar').version).toMatch(/^4\./)
    const glob = metadata(createRequire(requireFrom.resolve('@electron/asar')), 'glob')
    expect(requireFrom('semver').gte(glob.version, '14.0.3'), glob.manifest).toBe(true)
    const asar = requireFrom('@electron/asar')
    await temporary(async directory => {
      const source = path.join(directory, 'input files'), archive = path.join(directory, 'test archive.asar')
      const output = path.join(directory, 'extracted files')
      const contents = new Map([['.metadata', Buffer.from('hidden')], ['nested/message.txt', Buffer.from('roundtrip')], ['payload.bin', Buffer.from([0, 128, 255])]])
      for (const [name, content] of contents) {
        const file = path.join(source, name)
        fs.mkdirSync(path.dirname(file), { recursive: true })
        fs.writeFileSync(file, content)
      }
      try {
        await asar.createPackage(source, archive)
        expect(asar.listPackage(archive, { isPack: false }).map((n: string) => n.replace(/\\/g, '/')).sort())
          .toEqual(['/.metadata', '/nested', '/nested/message.txt', '/payload.bin'])
        for (const [name, content] of contents) expect(asar.extractFile(archive, name), name).toEqual(content)
        asar.extractAll(archive, output)
        for (const [name, content] of contents) expect(fs.readFileSync(path.join(output, name)), name).toEqual(content)
      } finally { asar.uncache(archive) }
    })
  }, 20_000)

  it('preserves FileMatcher include/exclude, directory and dotfile behavior', async () => {
    const { FileMatcher } = builder()('app-builder-lib/out/fileMatcher.js')
    await temporary(directory => {
      const from = path.join(directory, 'input files'), to = path.join(directory, 'output files')
      for (const name of ['included/main.txt', 'included/deep/child.txt', 'included/deep/secret.txt', 'included/.notes.txt', 'included/.hidden/child.txt', 'included/readme.md', 'other/main.txt', '.config']) {
        const file = path.join(from, name)
        fs.mkdirSync(path.dirname(file), { recursive: true })
        fs.writeFileSync(file, name)
      }
      const expand = (value: string) => value.replaceAll('__ROOT__', directory)
      const matcher = new FileMatcher(path.join('__ROOT__', 'input files'), path.join('__ROOT__', 'output files'), expand, ['included/**/*.txt', '!included/**/secret*.txt', '.config'])
      expect(matcher.from).toBe(from)
      expect(matcher.to).toBe(to)
      const filter = matcher.createFilter()
      const cases: [string, boolean][] = [['', true], ['included', true], ['included/deep', true], ['included/.hidden', true], ['included/main.txt', true], ['included/deep/child.txt', true], ['included/deep/secret.txt', false], ['included/.notes.txt', true], ['included/.hidden/child.txt', true], ['included/readme.md', false], ['other', false], ['other/main.txt', false], ['.config', true]]
      for (const [name, included] of cases) {
        const file = path.join(from, name)
        expect(filter(file, fs.statSync(file)), name || '<root>').toBe(included)
      }
      const directoryFilter = new FileMatcher(from, to, expand, ['included']).createFilter()
      for (const name of ['included', 'included/deep/child.txt', 'included/.notes.txt']) {
        const file = path.join(from, name)
        expect(directoryFilter(file, fs.statSync(file)), name).toBe(true)
      }
    })
  })

  it('applies ESLint flat files/ignores through actual lintText', async () => {
    const { ESLint } = consumer('eslint')
    await temporary(async directory => {
      const eslint = new ESLint({ cwd: directory, overrideConfigFile: true, overrideConfig: [
        { ignores: ['ignored/**'] },
        { files: ['src/**/*.{js,cjs}'], ignores: ['src/**/excluded.js'], rules: { 'no-undef': 'error' } },
      ] })
      const lint = (name: string) => eslint.lintText('missingGlobal()', { filePath: path.join(directory, name), warnIgnored: false })
      for (const name of ['src/main.js', 'src/deep/main.cjs', 'src/.hidden.js']) {
        const results = await lint(name)
        expect(results, name).toHaveLength(1)
        expect(results[0].messages.map((m: { ruleId: string }) => m.ruleId), name).toEqual(['no-undef'])
      }
      expect(await lint('ignored/main.js')).toEqual([])
      for (const name of ['src/deep/excluded.js', 'outside/main.js']) {
        const results = await lint(name)
        expect(results, name).toHaveLength(1)
        expect(results[0].messages, name).toEqual([])
      }
    })
  })

  it('renders EJS and expands actual Jake filelist patterns in spaced directories', async () => {
    const ejs = builder().resolve('ejs')
    const jake = createRequire(createRequire(ejs).resolve('jake'))
    await temporary(directory => child(String.raw`
      const ejs = require(entries.ejs), {FileList} = require(entries.filelist)
      assert.equal(ejs.render('<%= name %>:<% for(const item of items){ %><%= item %>;<% } %>', {name:'<user>',items:['one','two']}), '&lt;user&gt;:one;two;')
      fs.mkdirSync('templates/nested', {recursive:true})
      for(const name of ['main.ejs','.hidden.ejs','nested/partial.ejs','nested/skip-me.ejs','notes.txt']) fs.writeFileSync(path.join('templates',name),name)
      const files = new FileList().include('templates/**/*.ejs',{dot:true}).exclude('templates/**/skip*.ejs').toArray().map(n=>n.replace(/\\/g,'/')).sort()
      assert.deepEqual(files,['templates/.hidden.ejs','templates/main.ejs','templates/nested/partial.ejs'])
      console.log('passed')
    `, {ejs,filelist:jake.resolve('filelist')}, directory))
  }, 20_000)

  it('tracks and cleans actual temp directories through temp with async and sync APIs', async () => {
    await temporary(directory => child(String.raw`
      const temp=require(entries).track()
      try {
        const asynchronous=await temp.mkdir({dir:process.cwd(),prefix:'async tracked '})
        assert.equal(asynchronous.includes(' '),true)
        fs.mkdirSync(path.join(asynchronous,'nested directory'))
        fs.writeFileSync(path.join(asynchronous,'nested directory','.payload'),'async')
        assert.deepEqual(await temp.cleanup(),{files:0,dirs:1})
        assert.equal(fs.existsSync(asynchronous),false)
        const synchronous=temp.mkdirSync({dir:process.cwd(),prefix:'sync tracked '})
        fs.mkdirSync(path.join(synchronous,'nested directory'))
        fs.writeFileSync(path.join(synchronous,'nested directory','.payload'),'sync')
        assert.deepEqual(temp.cleanupSync(),{files:0,dirs:1})
        assert.equal(fs.existsSync(synchronous),false)
        console.log('passed')
      } finally {temp.cleanupSync();temp.track(false)}
    `, legacyTemp(), directory))
  }, 20_000)

  it('bounds exact GHSA-g3hv fixtures for every minimatch in a timeout-limited child', () => {
    child(String.raw`
      for(const manifest of entries){
        const {Minimatch}=createRequire(manifest)('minimatch')
        const options={optimizationLevel:2,braceExpandMax:64}
        assert.equal(new Minimatch(Array(30).fill('**/../a/b').join('/'),options).set.length,64,manifest)
        const traversal=new Minimatch('**/../a/b/**/../c/d',options)
        assert.equal(traversal.set.length,4,manifest)
        assert.equal(traversal.match('../a/b/../c/d'),true,manifest)
        assert.equal(traversal.match('x/a/b/y/c/d'),true,manifest)
        const braces=new Minimatch('{x,*}/{0..999}',{optimizationLevel:2})
        assert.equal(braces.set.length,2000,manifest)
        assert.equal(braces.match('y/999'),true,manifest)
      }
      console.log('passed')
    `, minimatches(), root)
  }, 20_000)
})
