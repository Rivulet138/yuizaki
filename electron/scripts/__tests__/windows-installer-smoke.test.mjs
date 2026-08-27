import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  cleanupOwnedTempRoot,
  executeWindowsInstallerSmoke,
  inspectInstalledApplication,
  parseArguments,
  prepareOwnedTempRoot,
  resolveOwnedPath,
} from '../windows-installer-smoke.mjs'
import { previousPrereleaseVersion } from '../build-windows-installer-smoke-fixtures.mjs'

const makeInstaller = (root, name, contents) => {
  const target = path.join(root, name)
  fs.writeFileSync(target, contents)
  return target
}

const writeInstalledLayout = (installDirectory, generation) => {
  fs.mkdirSync(path.join(installDirectory, 'resources', 'runtime', 'python'), { recursive: true })
  fs.writeFileSync(path.join(installDirectory, 'Yuizaki.exe'), `app-${generation}`)
  fs.writeFileSync(path.join(installDirectory, 'resources', 'app.asar'), `asar-${generation}`)
  fs.writeFileSync(path.join(installDirectory, 'resources', 'runtime', 'python', 'app.py'), 'pass\n')
  fs.writeFileSync(path.join(installDirectory, 'resources', 'runtime', 'YuizakiLauncher.exe'), 'launcher')
  fs.writeFileSync(path.join(installDirectory, 'Uninstall Yuizaki.exe'), 'uninstaller')
}

test('argument contract requires explicit installers and a bounded launch timeout', () => {
  assert.deepEqual(parseArguments([
    '--old-installer=C:\\tmp\\old.exe',
    '--new-installer', 'C:\\tmp\\new.exe',
    '--temp-root', 'C:\\tmp\\yuizaki-installer-smoke-contract',
    '--launch-timeout-ms', '2500',
  ]), {
    oldInstaller: 'C:\\tmp\\old.exe',
    newInstaller: 'C:\\tmp\\new.exe',
    tempRoot: 'C:\\tmp\\yuizaki-installer-smoke-contract',
    temporaryBase: undefined,
    evidencePath: undefined,
    launchTimeoutMs: 2500,
  })
  assert.throws(() => parseArguments(['--old-installer', 'old.exe']), /Missing required argument/)
  assert.throws(() => parseArguments([
    '--old-installer', 'old.exe', '--new-installer', 'new.exe', '--temp-root', 'root', '--launch-timeout-ms', '1',
  ]), /between 2000 and 60000/)
})

test('owned temp-root guard rejects broad, outside, reused, and traversal paths', () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-guard-base-'))
  try {
    assert.throws(() => prepareOwnedTempRoot(base, base), /child of the approved temporary base/)
    assert.throws(() => prepareOwnedTempRoot(path.join(base, 'wrong-prefix'), base), /basename must start/)
    const requested = path.join(base, 'yuizaki-installer-smoke-owned')
    const owned = prepareOwnedTempRoot(requested, base)
    assert.equal(owned.root, fs.realpathSync.native(requested))
    assert.throws(() => prepareOwnedTempRoot(requested, base), /must not already contain files/)
    assert.throws(() => resolveOwnedPath(requested, '..', 'escape'), /escapes/)
    assert.throws(() => cleanupOwnedTempRoot(requested, 'wrong-run'), /does not match/)
    cleanupOwnedTempRoot(requested, owned.marker.runId)
    assert.equal(fs.existsSync(requested), false)
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

test('owned temp-root accepts only an explicitly approved alternate base', () => {
  const alternateBase = fs.mkdtempSync(path.join(process.cwd(), '.yuizaki-installer-alt-base-'))
  const unapprovedBase = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-unapproved-base-'))
  const requested = path.join(alternateBase, 'yuizaki-installer-smoke-alternate')
  try {
    assert.throws(() => prepareOwnedTempRoot(requested, unapprovedBase), /child of the approved temporary base/)
    const owned = prepareOwnedTempRoot(requested, alternateBase)
    assert.equal(owned.root, fs.realpathSync.native(requested))
    assert.throws(() => cleanupOwnedTempRoot(requested, owned.marker.runId, unapprovedBase), /unowned path/)
    cleanupOwnedTempRoot(requested, owned.marker.runId, alternateBase)
    assert.equal(fs.existsSync(requested), false)
  } finally {
    fs.rmSync(alternateBase, { recursive: true, force: true })
    fs.rmSync(unapprovedBase, { recursive: true, force: true })
  }
})

test('owned temp-root rejects a symlink or junction before resolving it', (context) => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-link-base-'))
  const target = path.join(base, 'target')
  const linkedRoot = path.join(base, 'yuizaki-installer-smoke-linked')
  fs.mkdirSync(target)
  try {
    try {
      fs.symlinkSync(target, linkedRoot, process.platform === 'win32' ? 'junction' : 'dir')
    } catch (error) {
      if (error?.code === 'EPERM') {
        context.skip('This Windows host does not permit creating a junction')
        return
      }
      throw error
    }
    assert.throws(() => prepareOwnedTempRoot(linkedRoot, base), /real directory, not a link/)
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

test('installed layout inspection requires app, archive, Python runtime, and launcher', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-layout-'))
  try {
    writeInstalledLayout(root, 'old')
    const inspected = inspectInstalledApplication(root)
    assert.equal(path.basename(inspected.application), 'Yuizaki.exe')
    fs.rmSync(inspected.runtimeLauncher)
    assert.throws(() => inspectInstalledApplication(root), /Installed artifact is missing/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('host lifecycle contract verifies upgrade replacement and preserves isolated user data', async () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-contract-base-'))
  const oldInstaller = makeInstaller(base, 'old.exe', 'old-installer')
  const newInstaller = makeInstaller(base, 'new.exe', 'new-installer')
  const shortcut = path.join(base, 'Yuizaki.lnk')
  const events = []
  const host = {
    platform: 'win32',
    shortcutPaths: () => [shortcut],
    async install(installer, installDirectory) {
      const generation = path.basename(installer, '.exe')
      events.push(`install:${generation}`)
      fs.rmSync(installDirectory, { recursive: true, force: true })
      writeInstalledLayout(installDirectory, generation)
      fs.writeFileSync(shortcut, generation)
    },
    async launch(application) {
      events.push(`launch:${fs.readFileSync(application, 'utf8')}`)
    },
    async uninstall(uninstaller) {
      events.push('uninstall')
      fs.rmSync(path.dirname(uninstaller), { recursive: true, force: true })
      setTimeout(() => fs.rmSync(shortcut, { force: true }), 50)
    },
  }
  try {
    const evidence = await executeWindowsInstallerSmoke({
      oldInstaller,
      newInstaller,
      tempRoot: path.join(base, 'yuizaki-installer-smoke-run'),
      temporaryBase: base,
      launchTimeoutMs: 2_000,
    }, host)
    assert.equal(evidence.status, 'passed')
    assert.equal(evidence.rollbackQualification, 'not_claimed')
    assert.ok(evidence.checks.includes('old-install-created-expected-shortcuts'))
    assert.ok(evidence.checks.includes('upgrade-preserved-expected-shortcuts'))
    assert.ok(evidence.checks.includes('uninstall-cleaned-created-shortcuts'))
    assert.deepEqual(events, ['install:old', 'launch:app-old', 'install:new', 'launch:app-new', 'uninstall'])
    assert.equal(fs.existsSync(evidence.paths.installDirectory), false)
    assert.equal(fs.existsSync(path.join(evidence.paths.userDataDirectory, 'installer-smoke-sentinel.json')), true)
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

test('host lifecycle contract fails when an expected shortcut is missing', async () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-installer-shortcut-contract-base-'))
  const oldInstaller = makeInstaller(base, 'old.exe', 'old-installer')
  const newInstaller = makeInstaller(base, 'new.exe', 'new-installer')
  const desktopShortcut = path.join(base, 'Desktop', 'Yuizaki.lnk')
  const startMenuShortcut = path.join(base, 'Start Menu', 'Yuizaki.lnk')
  const host = {
    platform: 'win32',
    shortcutPaths: () => [desktopShortcut, startMenuShortcut],
    async install(installer, installDirectory) {
      writeInstalledLayout(installDirectory, path.basename(installer, '.exe'))
      fs.mkdirSync(path.dirname(desktopShortcut), { recursive: true })
      fs.writeFileSync(desktopShortcut, 'desktop')
    },
    async launch() {},
    async uninstall(uninstaller) {
      fs.rmSync(path.dirname(uninstaller), { recursive: true, force: true })
      fs.rmSync(desktopShortcut, { force: true })
    },
  }
  try {
    await assert.rejects(executeWindowsInstallerSmoke({
      oldInstaller,
      newInstaller,
      tempRoot: path.join(base, 'yuizaki-installer-smoke-run'),
      temporaryBase: base,
      launchTimeoutMs: 2_000,
    }, host), /did not create expected shortcuts after old install.*Start Menu/u)
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
})

test('fixture versions use an earlier prerelease without inventing rollback qualification', () => {
  assert.equal(previousPrereleaseVersion('0.1.0'), '0.1.0-installer-smoke.0')
  assert.equal(previousPrereleaseVersion('2.4.3'), '2.4.2-installer-smoke.0')
  assert.throws(() => previousPrereleaseVersion('2.4.3-beta.1'), /plain semver/)
})
