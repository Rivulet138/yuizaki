import { createHash, randomUUID } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT_PREFIX = 'yuizaki-installer-smoke-'
const OWNER_MARKER = '.yuizaki-installer-smoke-owner.json'
const DEFAULT_COMMAND_TIMEOUT_MS = 240_000
const DEFAULT_LAUNCH_TIMEOUT_MS = 10_000

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

export const parseArguments = (argumentsList) => {
  const values = new Map()
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index]
    if (!argument.startsWith('--')) throw new Error(`Unexpected positional argument: ${argument}`)
    const [rawName, inlineValue] = argument.split('=', 2)
    const name = rawName.slice(2)
    if (values.has(name)) throw new Error(`Duplicate argument: --${name}`)
    if (inlineValue !== undefined) {
      values.set(name, inlineValue)
      continue
    }
    const value = argumentsList[index + 1]
    if (!value || value.startsWith('--')) throw new Error(`Missing value for --${name}`)
    values.set(name, value)
    index += 1
  }

  const required = ['old-installer', 'new-installer', 'temp-root']
  for (const name of required) {
    if (!values.get(name)) throw new Error(`Missing required argument: --${name}`)
  }
  const allowed = new Set([...required, 'temporary-base', 'evidence', 'launch-timeout-ms'])
  for (const name of values.keys()) {
    if (!allowed.has(name)) throw new Error(`Unknown argument: --${name}`)
  }
  const launchTimeoutMs = values.has('launch-timeout-ms')
    ? Number.parseInt(values.get('launch-timeout-ms'), 10)
    : DEFAULT_LAUNCH_TIMEOUT_MS
  if (!Number.isSafeInteger(launchTimeoutMs) || launchTimeoutMs < 2_000 || launchTimeoutMs > 60_000) {
    throw new Error('--launch-timeout-ms must be an integer between 2000 and 60000')
  }
  return {
    oldInstaller: values.get('old-installer'),
    newInstaller: values.get('new-installer'),
    tempRoot: values.get('temp-root'),
    temporaryBase: values.get('temporary-base'),
    evidencePath: values.get('evidence'),
    launchTimeoutMs,
  }
}

const isPathInside = (parent, candidate) => {
  const relative = path.relative(parent, candidate)
  return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative)
}

export const prepareOwnedTempRoot = (requestedRoot, temporaryBase = os.tmpdir()) => {
  if (!path.isAbsolute(requestedRoot)) throw new Error('--temp-root must be an absolute path')
  const baseStats = fs.lstatSync(temporaryBase, { throwIfNoEntry: false })
  if (!baseStats?.isDirectory() || baseStats.isSymbolicLink()) {
    throw new Error('--temporary-base must be an existing real directory')
  }
  const base = fs.realpathSync.native(temporaryBase)
  const requested = path.resolve(requestedRoot)
  const requestedParent = path.dirname(requested)
  const parentStats = fs.lstatSync(requestedParent, { throwIfNoEntry: false })
  if (!parentStats?.isDirectory() || parentStats.isSymbolicLink()) {
    throw new Error('--temp-root parent must be an existing real directory')
  }
  const requestedStats = fs.lstatSync(requested, { throwIfNoEntry: false })
  if (requestedStats?.isSymbolicLink()) throw new Error('--temp-root must be a real directory, not a link')
  const root = requestedStats
    ? fs.realpathSync.native(requested)
    : path.join(fs.realpathSync.native(requestedParent), path.basename(requested))
  if (!isPathInside(base, root)) throw new Error(`--temp-root must be a child of the approved temporary base: ${base}`)
  if (!path.basename(root).startsWith(ROOT_PREFIX)) {
    throw new Error(`--temp-root basename must start with ${ROOT_PREFIX}`)
  }
  if (fs.existsSync(root)) {
    const stats = fs.lstatSync(root)
    if (!stats.isDirectory() || stats.isSymbolicLink()) throw new Error('--temp-root must be a real directory')
    if (fs.readdirSync(root).length !== 0) throw new Error('--temp-root must not already contain files')
  } else {
    fs.mkdirSync(root, { recursive: false })
  }
  const marker = { schemaVersion: 1, owner: 'yuizaki-windows-installer-smoke', runId: randomUUID() }
  fs.writeFileSync(path.join(root, OWNER_MARKER), `${JSON.stringify(marker)}\n`, { encoding: 'utf8', flag: 'wx' })
  return { root, marker }
}

export const resolveOwnedPath = (ownedRoot, ...segments) => {
  const markerPath = path.join(ownedRoot, OWNER_MARKER)
  if (!fs.existsSync(markerPath)) throw new Error(`Owned-root marker is missing: ${markerPath}`)
  const candidate = path.resolve(ownedRoot, ...segments)
  if (!isPathInside(ownedRoot, candidate)) throw new Error(`Path escapes the owned temp root: ${candidate}`)
  return candidate
}

export const cleanupOwnedTempRoot = (ownedRoot, expectedRunId, temporaryBase = os.tmpdir()) => {
  const baseStats = fs.lstatSync(temporaryBase, { throwIfNoEntry: false })
  if (!baseStats?.isDirectory() || baseStats.isSymbolicLink()) {
    throw new Error('Refusing cleanup with an invalid temporary base')
  }
  const rootStats = fs.lstatSync(ownedRoot, { throwIfNoEntry: false })
  if (!rootStats?.isDirectory() || rootStats.isSymbolicLink()) {
    throw new Error(`Refusing to clean a linked or missing path: ${ownedRoot}`)
  }
  const root = fs.realpathSync.native(ownedRoot)
  const base = fs.realpathSync.native(temporaryBase)
  if (!isPathInside(base, root) || !path.basename(root).startsWith(ROOT_PREFIX)) {
    throw new Error(`Refusing to clean an unowned path: ${root}`)
  }
  const markerPath = path.join(root, OWNER_MARKER)
  const markerStats = fs.lstatSync(markerPath)
  if (!markerStats.isFile() || markerStats.isSymbolicLink()) throw new Error(`Invalid owned-root marker: ${markerPath}`)
  const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'))
  if (marker.owner !== 'yuizaki-windows-installer-smoke' || marker.runId !== expectedRunId) {
    throw new Error(`Owned-root marker does not match this run: ${markerPath}`)
  }
  fs.rmSync(root, { recursive: true, force: false, maxRetries: 10, retryDelay: 100 })
}

const validateInstaller = (installerPath, label) => {
  if (!path.isAbsolute(installerPath)) throw new Error(`${label} installer path must be absolute`)
  const resolved = fs.realpathSync.native(installerPath)
  const stats = fs.lstatSync(resolved)
  if (!stats.isFile() || stats.isSymbolicLink() || path.extname(resolved).toLowerCase() !== '.exe') {
    throw new Error(`${label} installer must be a regular .exe file: ${resolved}`)
  }
  return resolved
}

const sha256 = (filePath) => createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')

const waitForExit = (child, timeoutMs, description) => new Promise((resolve, reject) => {
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    child.kill()
  }, timeoutMs)
  child.once('error', (error) => {
    clearTimeout(timer)
    reject(error)
  })
  child.once('exit', (code, signal) => {
    clearTimeout(timer)
    if (timedOut) reject(new Error(`${description} timed out after ${timeoutMs}ms`))
    else if (code !== 0) reject(new Error(`${description} failed (code=${code}, signal=${signal ?? 'none'})`))
    else resolve()
  })
})

const runExecutable = async (executable, argumentsList, description, timeoutMs = DEFAULT_COMMAND_TIMEOUT_MS) => {
  const child = spawn(executable, argumentsList, {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  })
  let output = ''
  child.stdout.on('data', (chunk) => { output += chunk.toString() })
  child.stderr.on('data', (chunk) => { output += chunk.toString() })
  try {
    await waitForExit(child, timeoutMs, description)
  } catch (error) {
    const suffix = output.trim() ? `\n${output.slice(-4_000)}` : ''
    throw new Error(`${error.message}${suffix}`, { cause: error })
  }
}

const terminateProcessTree = async (child) => {
  if (!child || child.exitCode !== null) return
  const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
    windowsHide: true,
    stdio: 'ignore',
    shell: false,
  })
  try {
    await waitForExit(killer, 15_000, 'taskkill')
  } catch {
    child.kill()
  }
}

const resolveWindowsKnownFolders = () => {
  const result = spawnSync('powershell.exe', [
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    "[Environment]::GetFolderPath('DesktopDirectory'); [Environment]::GetFolderPath('Programs')",
  ], {
    windowsHide: true,
    encoding: 'utf8',
    shell: false,
  })
  if (result.status !== 0) return []
  return result.stdout.split(/\r?\n/u).map((value) => value.trim()).filter(Boolean)
}

const defaultWindowsHost = {
  platform: process.platform,
  async install(installer, installDirectory) {
    await runExecutable(installer, ['/S', `/D=${installDirectory}`], `install ${path.basename(installer)}`)
  },
  async launch(application, userDataDirectory, timeoutMs) {
    const child = spawn(application, [`--user-data-dir=${userDataDirectory}`], {
      windowsHide: true,
      stdio: 'ignore',
      shell: false,
    })
    let earlyExit
    child.once('exit', (code, signal) => { earlyExit = { code, signal } })
    await sleep(timeoutMs)
    if (earlyExit) {
      throw new Error(`installed application exited before readiness window (code=${earlyExit.code}, signal=${earlyExit.signal ?? 'none'})`)
    }
    await terminateProcessTree(child)
  },
  async uninstall(uninstaller) {
    await runExecutable(uninstaller, ['/S'], `uninstall ${path.basename(uninstaller)}`)
  },
  shortcutPaths() {
    const knownFolders = resolveWindowsKnownFolders()
    const desktop = knownFolders[0] || (process.env.USERPROFILE && path.join(process.env.USERPROFILE, 'Desktop'))
    const programs = knownFolders[1] || (process.env.APPDATA && path.join(process.env.APPDATA, 'Microsoft', 'Windows', 'Start Menu', 'Programs'))
    return [desktop, programs].filter(Boolean).map((folder) => path.join(folder, 'Yuizaki.lnk'))
  },
}

export const inspectInstalledApplication = (installDirectory) => {
  const application = path.join(installDirectory, 'Yuizaki.exe')
  const appArchive = path.join(installDirectory, 'resources', 'app.asar')
  const runtimeEntry = path.join(installDirectory, 'resources', 'runtime', 'python', 'app.py')
  const runtimeLauncher = path.join(installDirectory, 'resources', 'runtime', 'YuizakiLauncher.exe')
  for (const requiredPath of [application, appArchive, runtimeEntry, runtimeLauncher]) {
    if (!fs.statSync(requiredPath, { throwIfNoEntry: false })?.isFile()) {
      throw new Error(`Installed artifact is missing: ${requiredPath}`)
    }
  }
  return { application, appArchive, runtimeEntry, runtimeLauncher, appArchiveSha256: sha256(appArchive) }
}

export const findUninstaller = (installDirectory) => {
  const matches = fs.readdirSync(installDirectory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && /^Uninstall .+\.exe$/i.test(entry.name))
    .map((entry) => path.join(installDirectory, entry.name))
  if (matches.length !== 1) throw new Error(`Expected exactly one NSIS uninstaller in ${installDirectory}, found ${matches.length}`)
  return matches[0]
}

const waitForMissing = async (target, timeoutMs = 30_000) => {
  const deadline = Date.now() + timeoutMs
  while (fs.existsSync(target) && Date.now() < deadline) await sleep(250)
  if (fs.existsSync(target)) throw new Error(`Path still exists after uninstall: ${target}`)
}

const waitForAllMissing = async (targets, timeoutMs = 30_000) => {
  const deadline = Date.now() + timeoutMs
  let remaining = targets.filter((target) => fs.existsSync(target))
  while (remaining.length > 0 && Date.now() < deadline) {
    await sleep(250)
    remaining = targets.filter((target) => fs.existsSync(target))
  }
  if (remaining.length > 0) throw new Error(`Uninstaller left shortcuts behind: ${remaining.join(', ')}`)
}

const requireExpectedShortcuts = (targets, phase) => {
  if (targets.length === 0) throw new Error(`No expected shortcut paths could be resolved after ${phase}`)
  const missing = targets.filter((target) => !fs.statSync(target, { throwIfNoEntry: false })?.isFile())
  if (missing.length > 0) throw new Error(`Installer did not create expected shortcuts after ${phase}: ${missing.join(', ')}`)
}

export const executeWindowsInstallerSmoke = async (configuration, host = defaultWindowsHost) => {
  if (host.platform !== 'win32') throw new Error('Windows installer smoke can only execute on Windows')
  const oldInstaller = validateInstaller(path.resolve(configuration.oldInstaller), 'Old')
  const newInstaller = validateInstaller(path.resolve(configuration.newInstaller), 'New')
  if (oldInstaller === newInstaller) throw new Error('Old and new installer paths must be different')
  const oldInstallerSha256 = sha256(oldInstaller)
  const newInstallerSha256 = sha256(newInstaller)
  if (oldInstallerSha256 === newInstallerSha256) throw new Error('Old and new installer contents must be different')

  const { root, marker } = prepareOwnedTempRoot(path.resolve(configuration.tempRoot), configuration.temporaryBase)
  const installDirectory = resolveOwnedPath(root, 'install')
  const userDataDirectory = resolveOwnedPath(root, 'user-data')
  fs.mkdirSync(userDataDirectory)
  const sentinelPath = resolveOwnedPath(root, 'user-data', 'installer-smoke-sentinel.json')
  const sentinel = `${JSON.stringify({ schemaVersion: 1, runId: marker.runId, value: randomUUID() })}\n`
  fs.writeFileSync(sentinelPath, sentinel, { encoding: 'utf8', flag: 'wx' })
  const sentinelSha256 = sha256(sentinelPath)
  const shortcutPaths = host.shortcutPaths?.() ?? []
  const shortcutsBefore = new Map(shortcutPaths.map((shortcutPath) => [shortcutPath, fs.existsSync(shortcutPath)]))
  const checks = []

  try {
    await host.install(oldInstaller, installDirectory)
    const oldApplication = inspectInstalledApplication(installDirectory)
    requireExpectedShortcuts(shortcutPaths, 'old install')
    checks.push('old-install-layout', 'old-install-created-expected-shortcuts')
    await host.launch(oldApplication.application, userDataDirectory, configuration.launchTimeoutMs ?? DEFAULT_LAUNCH_TIMEOUT_MS)
    checks.push('old-bounded-launch')

    await host.install(newInstaller, installDirectory)
    const newApplication = inspectInstalledApplication(installDirectory)
    if (oldApplication.appArchiveSha256 === newApplication.appArchiveSha256) {
      throw new Error('Upgrade did not replace resources/app.asar')
    }
    if (sha256(sentinelPath) !== sentinelSha256) throw new Error('User-data sentinel changed during upgrade')
    requireExpectedShortcuts(shortcutPaths, 'upgrade')
    checks.push('upgrade-replaced-app', 'upgrade-preserved-user-data', 'upgrade-preserved-expected-shortcuts')
    await host.launch(newApplication.application, userDataDirectory, configuration.launchTimeoutMs ?? DEFAULT_LAUNCH_TIMEOUT_MS)
    checks.push('new-bounded-launch')

    const shortcutsCreated = shortcutPaths.filter((shortcutPath) => !shortcutsBefore.get(shortcutPath) && fs.existsSync(shortcutPath))
    await host.uninstall(findUninstaller(installDirectory))
    await waitForMissing(installDirectory)
    if (sha256(sentinelPath) !== sentinelSha256) throw new Error('User-data sentinel changed during uninstall')
    checks.push('uninstall-cleaned-install-dir', 'uninstall-preserved-user-data')
    if (shortcutsCreated.length > 0) {
      await waitForAllMissing(shortcutsCreated)
      checks.push('uninstall-cleaned-created-shortcuts')
    }

    return {
      schemaVersion: 1,
      evidenceKind: 'windows_host_smoke',
      status: 'passed',
      runId: marker.runId,
      installers: {
        old: { path: oldInstaller, sha256: oldInstallerSha256 },
        new: { path: newInstaller, sha256: newInstallerSha256 },
      },
      paths: { tempRoot: root, installDirectory, userDataDirectory },
      checks,
      rollbackQualification: 'not_claimed',
    }
  } catch (error) {
    if (fs.existsSync(installDirectory)) {
      try {
        await host.uninstall(findUninstaller(installDirectory))
      } catch {
        // Preserve the owned temp root for diagnosis when NSIS cleanup cannot complete.
      }
    }
    throw error
  }
}

const main = async () => {
  const configuration = parseArguments(process.argv.slice(2))
  const evidence = await executeWindowsInstallerSmoke(configuration)
  cleanupOwnedTempRoot(evidence.paths.tempRoot, evidence.runId, configuration.temporaryBase)
  evidence.checks.push('harness-cleaned-owned-temp-root')
  if (configuration.evidencePath) {
    const evidencePath = path.resolve(configuration.evidencePath)
    fs.mkdirSync(path.dirname(evidencePath), { recursive: true })
    fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
  }
  console.log(JSON.stringify(evidence))
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`[windows-installer-smoke] ${error instanceof Error ? error.stack || error.message : String(error)}`)
    process.exitCode = 1
  })
}
