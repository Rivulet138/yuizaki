import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { validateProtectedCi } from '../verify-protected-ci.mjs'

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const ci = fs.readFileSync(path.join(repositoryRoot, '.github', 'workflows', 'ci.yml'), 'utf8')
const mutateQdrantJob = (transform) => {
  const marker = '  qdrant-integration:'
  const start = ci.indexOf(marker)
  assert.notEqual(start, -1)
  return ci.slice(0, start) + transform(ci.slice(start))
}

test('accepts the protected CI structure', () => {
  assert.deepEqual(validateProtectedCi(ci), [])
})

test('rejects a missing sentinel', () => {
  const mutated = ci.replace('# YUIZAKI_E2E_WINDOWS_BLOCK_END', '')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('WINDOWS_BLOCK_END')))
})

test('rejects a changed E2E command', () => {
  const mutated = ci.replace('run: xvfb-run -a npm run test:e2e', 'run: npm run test:e2e')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('xvfb-run -a npm run test:e2e')))
})

test('rejects moved protected anchors', () => {
  const mutated = ci.replace('- uses: actions/setup-go@v6', '- uses: actions/setup-go@v6\n      # YUIZAKI_E2E_WINDOWS_BLOCK_START')
    .replace('      # YUIZAKI_E2E_WINDOWS_BLOCK_START\n', '')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('anchors are missing or out of order')))
})

test('rejects an E2E run command hidden in a comment', () => {
  const mutated = ci.replace(
    '        run: npm run test:e2e',
    '        # run: npm run test:e2e',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must run exactly')))
})

for (const falseCondition of ['false', '${{ false }}', '0', '${{ 0 }}', 'off', "runner.os == 'Windows' && false"]) {
  test(`rejects a constant-false E2E condition: ${falseCondition}`, () => {
    const mutated = ci.replace(
      "      - name: Run Electron E2E (Windows)\n        if: runner.os == 'Windows'",
      `      - name: Run Electron E2E (Windows)\n        if: ${falseCondition}`,
    )
    assert.ok(validateProtectedCi(mutated).some((error) => (
      error.includes('constant-false') || error.includes('does not select Windows')
    )))
  })
}

test('does not accept E2E steps from the wrong job', () => {
  const mutated = ci
    .replace('  electron-build:', '  electron-build-shadow:')
    .replace('  node-mcp-test:', `  electron-build:
    strategy:
      matrix:
        os: [windows-latest, ubuntu-latest]
    steps:
      - run: npm ci
      - run: npm run install:runtime
      - run: npm run build

  node-mcp-test:`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run Electron E2E (Windows)')))
})

test('rejects an E2E step with the wrong working directory', () => {
  const mutated = ci.replace(
    "      - name: Run Electron E2E (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}/electron",
    "      - name: Run Electron E2E (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}",
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('electron working directory')))
})

test('accepts a block run with one exact active command', () => {
  const mutated = ci.replace(
    '        run: npm run test:e2e',
    '        run: |\n          # protected Windows E2E\n          npm run test:e2e',
  )
  assert.deepEqual(validateProtectedCi(mutated), [])
})

test('rejects a block run with a commented expected command and a different active command', () => {
  const mutated = ci.replace(
    '        run: xvfb-run -a npm run test:e2e',
    '        run: |\n          # xvfb-run -a npm run test:e2e\n          echo skipped',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must run exactly')))
})

test('rejects a duplicate pseudo E2E step', () => {
  const duplicate = `      - name: Run Electron E2E (Windows)
        if: false
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:e2e
`
  const mutated = ci.replace('      - name: Run Electron E2E (Windows)', `${duplicate}      - name: Run Electron E2E (Windows)`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one')))
})

test('rejects an E2E unit command hidden in a comment', () => {
  const mutated = ci.replace(
    '        run: npm run test:e2e:unit',
    '        # run: npm run test:e2e:unit',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Unit Tests (Windows) must run exactly')))
})

test('rejects a changed redaction command', () => {
  const mutated = ci.replace(
    '        run: npm run test:e2e:redaction',
    '        run: echo redaction-skipped',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Redaction Test (Windows) must run exactly')))
})

test('rejects a changed runtime recovery smoke command', () => {
  const mutated = ci.replace(
    '        run: npm run test:runtime-smoke',
    '        run: echo runtime-smoke-skipped',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Runtime Recovery Smoke (Windows) must run exactly')))
})

for (const stepName of ['Run Electron E2E Unit Tests', 'Run Python Runtime Recovery Smoke', 'Run Electron E2E Redaction Test']) {
  test(`rejects a constant-false ${stepName} condition`, () => {
    const mutated = ci.replace(
      `      - name: ${stepName} (Windows)\n        if: runner.os == 'Windows'`,
      `      - name: ${stepName} (Windows)\n        if: false`,
    )
    assert.ok(validateProtectedCi(mutated).some((error) => error.includes(`${stepName} (Windows)`)))
  })
}

test('rejects a redaction step with the wrong working directory', () => {
  const mutated = ci.replace(
    "      - name: Run Electron E2E Redaction Test (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}/electron",
    "      - name: Run Electron E2E Redaction Test (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}",
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Redaction Test (Windows) must use the electron working directory')))
})

test('rejects a runtime recovery smoke step with the wrong working directory', () => {
  const mutated = ci.replace(
    "      - name: Run Python Runtime Recovery Smoke (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}/electron",
    "      - name: Run Python Runtime Recovery Smoke (Windows)\n        if: runner.os == 'Windows'\n        working-directory: ${{ github.workspace }}",
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Runtime Recovery Smoke (Windows) must use the electron working directory')))
})

test('rejects a missing runtime recovery smoke step', () => {
  const step = `      - name: Run Python Runtime Recovery Smoke (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:runtime-smoke
`
  const mutated = ci.replace(step, '')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Run Python Runtime Recovery Smoke (Windows)')))
})

test('rejects a duplicate E2E unit step', () => {
  const duplicate = `      - name: Run Electron E2E Unit Tests (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:e2e:unit
`
  const mutated = ci.replace('      - name: Run Electron E2E Unit Tests (Windows)', `${duplicate}      - name: Run Electron E2E Unit Tests (Windows)`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Run Electron E2E Unit Tests (Windows)')))
})

test('does not accept a redaction step from the wrong job', () => {
  const step = `      - name: Run Electron E2E Redaction Test (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:e2e:redaction
`
  const mutated = ci
    .replace(step, '')
    .replace('  node-mcp-test:', `  wrong-redaction-job:
    steps:
${step}
  node-mcp-test:`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Run Electron E2E Redaction Test (Windows)')))
})

test('rejects redaction running before E2E unit tests', () => {
  const unitStep = `      - name: Run Electron E2E Unit Tests (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:e2e:unit
`
  const redactionStep = `      - name: Run Electron E2E Redaction Test (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:e2e:redaction
`
  const runtimeStep = `      - name: Run Python Runtime Recovery Smoke (Windows)
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/electron
        run: npm run test:runtime-smoke
`
  const mutated = ci.replace(`${unitStep}${runtimeStep}${redactionStep}`, `${redactionStep}${runtimeStep}${unitStep}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('build -> unit -> runtime smoke -> redaction -> default E2E order')))
})

test('requires both protected operating systems in the electron matrix', () => {
  const mutated = ci.replace('os: [windows-latest, ubuntu-latest]', 'os: [windows-latest]')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('ubuntu-latest')))
})

test('requires E2E steps to run after install and build prerequisites', () => {
  const build = '      - run: npm run build\n'
  const mutated = ci
    .replace(build, '')
    .replace('        run: npm run test:e2e\n', `        run: npm run test:e2e\n${build}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must run after npm run build')))
})

test('does not accept a constant-false fake build prerequisite', () => {
  const build = '      - run: npm run build\n'
  const fakeBuild = "      - if: false\n        run: npm run build\n"
  const mutated = ci
    .replace(build, fakeBuild)
    .replace('        run: npm run test:e2e\n', `        run: npm run test:e2e\n${build}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must run after npm run build')))
})

test('rejects a Windows launcher command hidden in a comment', () => {
  const mutated = ci.replace('        run: go test ./...', '        # run: go test ./...')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Test Windows launcher must run exactly')))
})

test('does not accept the Windows launcher step from the wrong job', () => {
  const launcherStep = `      - name: Test Windows launcher
        if: runner.os == 'Windows'
        working-directory: \${{ github.workspace }}/tools/yuizaki-launcher
        run: go test ./...
`
  const mutated = ci
    .replace(launcherStep, '')
    .replace('\n  electron-build:', `\n${launcherStep}  electron-build:`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Test Windows launcher')))
})

test('rejects a disabled Windows launcher step', () => {
  const mutated = ci.replace(
    "      - name: Test Windows launcher\n        if: runner.os == 'Windows'",
    '      - name: Test Windows launcher\n        if: false',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Test Windows launcher')))
})

test('rejects a Windows launcher step with the wrong working directory', () => {
  const mutated = ci.replace(
    '        working-directory: ${{ github.workspace }}/tools/yuizaki-launcher',
    '        working-directory: ${{ github.workspace }}',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Test Windows launcher has an invalid working directory')))
})

test('rejects a disabled setup-go prerequisite', () => {
  const mutated = ci.replace(
    "      - uses: actions/setup-go@v6\n        if: runner.os == 'Windows'",
    '      - uses: actions/setup-go@v6\n        if: false',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('actions/setup-go@v6')))
})

test('rejects a Linux library command hidden in a comment', () => {
  const mutated = ci.replace(
    '          sudo chmod 4755 electron/node_modules/electron/dist/chrome-sandbox',
    '          # sudo chmod 4755 electron/node_modules/electron/dist/chrome-sandbox',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install Linux GUI runtime libraries must run exactly')))
})

test('rejects a Python matrix row hidden in comments', () => {
  const matrixRow = `          - os: ubuntu-latest
            python-version: '3.13'
            requirements-lock: requirements-dev-lock-linux.txt`
  const commentedRow = matrixRow.split('\n').map((line) => `${line.slice(0, 10)}# ${line.slice(10)}`).join('\n')
  const mutated = ci.replace(matrixRow, commentedRow)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('matrix.include must exactly match')))
})

test('rejects an incorrect Python matrix lock combination', () => {
  const mutated = ci.replace(
    "          - os: windows-latest\n            python-version: '3.11'\n            requirements-lock: requirements-dev-lock-windows.txt",
    "          - os: windows-latest\n            python-version: '3.11'\n            requirements-lock: requirements-dev-lock-linux.txt",
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('matrix.include must exactly match')))
})

test('rejects a Python test command hidden in a comment', () => {
  const mutated = ci.replace('        run: pytest . -q --tb=short', '        # run: pytest . -q --tb=short')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run tests must run exactly')))
})

test('does not accept the pyright step from the wrong job', () => {
  const pyrightStep = `      - name: Type check with pyright
        run: pyright --pythonversion \${{ matrix.python-version }}
`
  const mutated = ci
    .replace(pyrightStep, '')
    .replace('\n  python-test:', `\n${pyrightStep}  python-test:`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Type check with pyright')))
})

test('rejects a missing ruff step', () => {
  const ruffStep = `      - name: Check Python runtime errors with ruff
        run: ruff check . --select E9,F63,F7,F82

`
  const mutated = ci.replace(ruffStep, '')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Check Python runtime errors with ruff')))
})

test('rejects a disabled pytest step', () => {
  const mutated = ci.replace(
    '      - name: Run tests\n        run: pytest . -q --tb=short',
    '      - name: Run tests\n        if: false\n        run: pytest . -q --tb=short',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run tests must run unconditionally')))
})

test('rejects an Install dependencies override to the repository root', () => {
  const mutated = ci.replace(
    '      - name: Install dependencies\n        run: |',
    '      - name: Install dependencies\n        working-directory: ${{ github.workspace }}\n        run: |',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install dependencies must run in the python working directory')))
})

test('rejects a ruff override to the Electron working directory', () => {
  const mutated = ci.replace(
    '      - name: Check Python runtime errors with ruff\n        run:',
    '      - name: Check Python runtime errors with ruff\n        working-directory: electron\n        run:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('ruff must run in the python working directory')))
})

test('rejects a pyright override to the node-mcp working directory', () => {
  const mutated = ci.replace(
    '      - name: Type check with pyright\n        run:',
    '      - name: Type check with pyright\n        working-directory: node-mcp\n        run:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('pyright must run in the python working directory')))
})

test('rejects a pytest override to the repository root shorthand', () => {
  const mutated = ci.replace(
    '      - name: Run tests\n        run:',
    '      - name: Run tests\n        working-directory: .\n        run:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run tests must run in the python working directory')))
})

test('accepts an explicit equivalent Python working directory override', () => {
  const mutated = ci.replace(
    '      - name: Type check with pyright\n        run:',
    '      - name: Type check with pyright\n        working-directory: ${{ github.workspace }}/python\n        run:',
  )
  assert.deepEqual(validateProtectedCi(mutated), [])
})

test('rejects an Install dependencies command hidden in a comment', () => {
  const mutated = ci.replace(
    '          python scripts/check_installed_lock.py --lock ${{ matrix.requirements-lock }}',
    '          # python scripts/check_installed_lock.py --lock ${{ matrix.requirements-lock }}',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install dependencies must run exactly')))
})

test('does not accept Install dependencies from the wrong job', () => {
  const installStep = `      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r \${{ matrix.requirements-lock }}
          pip check
          python scripts/check_installed_lock.py --lock \${{ matrix.requirements-lock }}

`
  const mutated = ci
    .replace(installStep, '')
    .replace('\n  python-test:', `\n${installStep}  python-test:`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one Install dependencies')))
})

test('rejects a disabled Install dependencies step', () => {
  const mutated = ci.replace(
    '      - name: Install dependencies\n        run: |',
    '      - name: Install dependencies\n        if: false\n        run: |',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install dependencies must run unconditionally')))
})

test('rejects ruff running before Install dependencies', () => {
  const installStep = `      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r \${{ matrix.requirements-lock }}
          pip check
          python scripts/check_installed_lock.py --lock \${{ matrix.requirements-lock }}

`
  const ruffStep = `      - name: Check Python runtime errors with ruff
        run: ruff check . --select E9,F63,F7,F82

`
  const mutated = ci.replace(`${installStep}${ruffStep}`, `${ruffStep}${installStep}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install dependencies -> ruff -> pyright -> pytest order')))
})

test('rejects pyright running before ruff', () => {
  const ruffStep = `      - name: Check Python runtime errors with ruff
        run: ruff check . --select E9,F63,F7,F82

`
  const pyrightStep = `      - name: Type check with pyright
        run: pyright --pythonversion \${{ matrix.python-version }}

`
  const mutated = ci.replace(`${ruffStep}${pyrightStep}`, `${pyrightStep}${ruffStep}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Install dependencies -> ruff -> pyright -> pytest order')))
})

test('rejects a missing Qdrant integration job', () => {
  const mutated = ci.replace('  qdrant-integration:', '  qdrant-integration-disabled:')
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('missing jobs.qdrant-integration')))
})

test('rejects duplicate Qdrant integration jobs', () => {
  const mutated = ci.replace(
    '  qdrant-integration:',
    '  qdrant-integration:\n    runs-on: ubuntu-latest\n    steps: []\n\n  qdrant-integration:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must occur exactly once')))
})

test('rejects a Qdrant integration job on the wrong runner', () => {
  const mutated = ci.replace(
    '  qdrant-integration:\n    name: Real Qdrant Recovery Integration\n    runs-on: ubuntu-latest',
    '  qdrant-integration:\n    name: Real Qdrant Recovery Integration\n    runs-on: windows-latest',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('runs-on must be ubuntu-latest')))
})

test('rejects a disabled Qdrant setup-python step', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '      - uses: actions/setup-python@v5\n        with:\n          python-version:',
    '      - uses: actions/setup-python@v5\n        if: false\n        with:\n          python-version:',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('actions/setup-python@v5 must run unconditionally without continue-on-error')))
})

test('rejects a disabled Qdrant integration job', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '    runs-on: ubuntu-latest',
    '    runs-on: ubuntu-latest\n    if: false',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('qdrant-integration must run unconditionally')))
})

test('rejects continue-on-error on the Qdrant integration job', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '    runs-on: ubuntu-latest',
    '    runs-on: ubuntu-latest\n    continue-on-error: true',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('qdrant-integration must not set continue-on-error')))
})

test('rejects continue-on-error on the Qdrant integration step', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '      - name: Run real Qdrant recovery integration\n        run:',
    '      - name: Run real Qdrant recovery integration\n        continue-on-error: true\n        run:',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run real Qdrant recovery integration must not set continue-on-error')))
})

test('rejects a shell override on the Qdrant integration step', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '      - name: Run real Qdrant recovery integration\n        run:',
    '      - name: Run real Qdrant recovery integration\n        shell: echo {0}\n        run:',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run real Qdrant recovery integration must not override the command shell')))
})

test('rejects a default shell override on the Qdrant integration job', () => {
  const mutated = mutateQdrantJob((job) => job.replace(
    '    runs-on: ubuntu-latest',
    '    runs-on: ubuntu-latest\n    defaults:\n      run:\n        shell: echo {0}',
  ))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('qdrant-integration must not override defaults.run.shell')))
})

test('rejects a missing Qdrant checkout step', () => {
  const mutated = mutateQdrantJob((job) => job.replace('      - uses: actions/checkout@v4\n\n', ''))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one actions/checkout@v4')))
})

test('rejects a missing Qdrant setup-python step', () => {
  const setupStep = `      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
          cache-dependency-path: python/requirements-dev-lock-linux.txt

`
  const mutated = mutateQdrantJob((job) => job.replace(setupStep, ''))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('exactly one actions/setup-python@v5')))
})

test('rejects an unpinned Qdrant Python version', () => {
  const mutated = mutateQdrantJob((job) => job.replace("          python-version: '3.12'", "          python-version: '3.x'"))
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('must pin Python 3.12')))
})

test('rejects a changed Qdrant integration command', () => {
  const mutated = ci.replace(
    '        run: python scripts/run_qdrant_integration.py',
    '        run: pytest python/tests/test_qdrant_integration.py -q',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run real Qdrant recovery integration must run exactly')))
})

test('rejects a disabled Qdrant integration step', () => {
  const mutated = ci.replace(
    '      - name: Run real Qdrant recovery integration\n        run:',
    '      - name: Run real Qdrant recovery integration\n        if: false\n        run:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run real Qdrant recovery integration must run unconditionally')))
})

test('rejects Qdrant integration before dependency install', () => {
  const installStep = `      - name: Install Qdrant integration dependencies
        working-directory: python
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev-lock-linux.txt
          pip check
          python scripts/check_installed_lock.py --lock requirements-dev-lock-linux.txt

`
  const integrationStep = `      - name: Run real Qdrant recovery integration
        run: python scripts/run_qdrant_integration.py
`
  const mutated = ci.replace(`${installStep}${integrationStep}`, `${integrationStep}\n${installStep.trimEnd()}`)
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('dependency install -> real integration order')))
})

test('rejects a Qdrant integration step in the Python directory', () => {
  const mutated = ci.replace(
    '      - name: Run real Qdrant recovery integration\n        run:',
    '      - name: Run real Qdrant recovery integration\n        working-directory: python\n        run:',
  )
  assert.ok(validateProtectedCi(mutated).some((error) => error.includes('Run real Qdrant recovery integration must run in the python working directory')))
})
