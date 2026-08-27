import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(electronRoot, '..')
const releaseRoot = path.join(repositoryRoot, 'release', 'installer-smoke')
const builderCli = path.join(electronRoot, 'node_modules', 'electron-builder', 'out', 'cli', 'cli.js')

export const previousPrereleaseVersion = (version) => {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version)
  if (!match) throw new Error(`Package version must be plain semver for installer smoke fixtures: ${version}`)
  const [, major, minor, patch] = match
  return `${major}.${minor}.${Math.max(0, Number.parseInt(patch, 10) - 1)}-installer-smoke.0`
}

const runBuilder = (version, outputDirectory) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [
    builderCli,
    '--win', 'nsis',
    `--config.extraMetadata.version=${version}`,
    `--config.directories.output=${outputDirectory}`,
  ], { cwd: electronRoot, stdio: 'inherit', shell: false, windowsHide: true })
  child.once('error', reject)
  child.once('exit', (code, signal) => {
    if (code === 0) resolve()
    else reject(new Error(`electron-builder failed for ${version} (code=${code}, signal=${signal ?? 'none'})`))
  })
})

export const findSingleInstaller = (outputDirectory) => {
  const installers = fs.readdirSync(outputDirectory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('.exe'))
    .map((entry) => path.join(outputDirectory, entry.name))
  if (installers.length !== 1) throw new Error(`Expected one installer in ${outputDirectory}, found ${installers.length}`)
  return installers[0]
}

const main = async () => {
  if (process.platform !== 'win32') throw new Error('Windows fixture installers can only be built on Windows')
  if (!fs.existsSync(builderCli)) throw new Error(`electron-builder CLI is missing: ${builderCli}`)

  const packageJson = JSON.parse(fs.readFileSync(path.join(electronRoot, 'package.json'), 'utf8'))
  const newVersion = process.env.YUIZAKI_SMOKE_NEW_VERSION || packageJson.version
  const oldVersion = process.env.YUIZAKI_SMOKE_OLD_VERSION || previousPrereleaseVersion(newVersion)
  if (oldVersion === newVersion) throw new Error('Smoke fixture versions must be different')

  const oldOutput = path.join(releaseRoot, 'old')
  const newOutput = path.join(releaseRoot, 'new')
  fs.mkdirSync(oldOutput, { recursive: true })
  fs.mkdirSync(newOutput, { recursive: true })
  await runBuilder(oldVersion, oldOutput)
  await runBuilder(newVersion, newOutput)

  const manifest = {
    schemaVersion: 1,
    oldVersion,
    newVersion,
    oldInstaller: findSingleInstaller(oldOutput),
    newInstaller: findSingleInstaller(newOutput),
  }
  fs.writeFileSync(path.join(releaseRoot, 'fixtures.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify(manifest))
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`[build-windows-installer-smoke-fixtures] ${error instanceof Error ? error.stack || error.message : String(error)}`)
    process.exitCode = 1
  })
}
