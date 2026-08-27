import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const requiredFragments = [
  "node-version: '22.13'",
]

const orderedMarkers = [
  ['# YUIZAKI_E2E_WINDOWS_BLOCK_START', '# YUIZAKI_E2E_WINDOWS_BLOCK_END'],
  ['# YUIZAKI_E2E_LINUX_BLOCK_START', '# YUIZAKI_E2E_LINUX_BLOCK_END'],
]

const structuredContractCount = 8

const count = (text, fragment) => text.split(fragment).length - 1

const indentation = (line) => line.match(/^ */)?.[0].length ?? 0

const stripYamlComment = (value) => {
  let singleQuoted = false
  let doubleQuoted = false
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]
    if (character === "'" && !doubleQuoted) singleQuoted = !singleQuoted
    if (character === '"' && !singleQuoted && value[index - 1] !== '\\') doubleQuoted = !doubleQuoted
    if (character === '#' && !singleQuoted && !doubleQuoted && (index === 0 || /\s/.test(value[index - 1]))) {
      return value.slice(0, index).trimEnd()
    }
  }
  return value.trimEnd()
}

const unquote = (value) => {
  const trimmed = value.trim()
  if (trimmed.length >= 2 && ((trimmed.startsWith("'") && trimmed.endsWith("'"))
    || (trimmed.startsWith('"') && trimmed.endsWith('"')))) return trimmed.slice(1, -1)
  return trimmed
}

const parseField = (line) => {
  const active = stripYamlComment(line.trim())
  const match = active.match(/^([\w-]+):(?:\s*(.*))?$/)
  return match ? { key: match[1], value: match[2] ?? '' } : null
}

const findBlock = (lines, parentIndent, key, start = 0, end = lines.length) => {
  for (let index = start; index < end; index += 1) {
    if (indentation(lines[index]) !== parentIndent) continue
    const field = parseField(lines[index])
    if (field?.key !== key) continue
    let blockEnd = index + 1
    while (blockEnd < end && (lines[blockEnd].trim() === '' || indentation(lines[blockEnd]) > parentIndent)) blockEnd += 1
    return { start: index, end: blockEnd, indent: parentIndent }
  }
  return null
}

const parseSteps = (lines, block) => {
  const steps = []
  const stepIndent = block.indent + 2
  for (let index = block.start + 1; index < block.end;) {
    const trimmed = lines[index].trim()
    if (indentation(lines[index]) !== stepIndent || !trimmed.startsWith('-') || trimmed.startsWith('#')) {
      index += 1
      continue
    }
    const afterDash = stripYamlComment(trimmed.slice(1).trim())
    if (!afterDash) {
      index += 1
      continue
    }
    let stepEnd = index + 1
    while (stepEnd < block.end && (lines[stepEnd].trim() === '' || indentation(lines[stepEnd]) > stepIndent)) stepEnd += 1
    const step = { index: steps.length, line: index + 1, fields: {}, runLines: [], withFields: {} }
    const inlineField = parseField(afterDash)
    if (inlineField) step.fields[inlineField.key] = unquote(inlineField.value)
    for (let cursor = index + 1; cursor < stepEnd; cursor += 1) {
      if (indentation(lines[cursor]) !== stepIndent + 2) continue
      const field = parseField(lines[cursor])
      if (!field) continue
      const value = unquote(field.value)
      step.fields[field.key] = value
      if (field.key === 'with') {
        for (let withIndex = cursor + 1; withIndex < stepEnd; withIndex += 1) {
          if (indentation(lines[withIndex]) !== stepIndent + 4) continue
          const withField = parseField(lines[withIndex])
          if (withField) step.withFields[withField.key] = unquote(withField.value)
        }
      }
      if (field.key === 'run') {
        if (/^[|>][-+]?\s*$/.test(value)) {
          for (let commandIndex = cursor + 1; commandIndex < stepEnd; commandIndex += 1) {
            if (indentation(lines[commandIndex]) <= stepIndent + 2 && lines[commandIndex].trim() !== '') break
            const command = stripYamlComment(lines[commandIndex].trim())
            if (command) step.runLines.push(command)
          }
        } else if (value) step.runLines.push(value)
      }
    }
    if (inlineField?.key === 'run' && inlineField.value) step.runLines.push(unquote(inlineField.value))
    steps.push(step)
    index = stepEnd
  }
  return steps
}

const parseInlineSequence = (value) => {
  const trimmed = stripYamlComment(value).trim()
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) return []
  return trimmed.slice(1, -1).split(',').map((item) => unquote(item)).filter(Boolean)
}

const parseMappingSequence = (lines, block) => {
  const entries = []
  const itemIndent = block.indent + 2
  for (let index = block.start + 1; index < block.end;) {
    const trimmed = lines[index].trim()
    if (indentation(lines[index]) !== itemIndent || !trimmed.startsWith('-') || trimmed.startsWith('#')) {
      index += 1
      continue
    }
    let itemEnd = index + 1
    while (itemEnd < block.end && (lines[itemEnd].trim() === '' || indentation(lines[itemEnd]) > itemIndent)) itemEnd += 1
    const entry = {}
    const inlineField = parseField(stripYamlComment(trimmed.slice(1).trim()))
    if (inlineField) entry[inlineField.key] = unquote(inlineField.value)
    for (let cursor = index + 1; cursor < itemEnd; cursor += 1) {
      if (indentation(lines[cursor]) !== itemIndent + 2) continue
      const field = parseField(lines[cursor])
      if (field) entry[field.key] = unquote(field.value)
    }
    entries.push(entry)
    index = itemEnd
  }
  return entries
}

const parseWorkflow = (text) => {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const jobsBlock = findBlock(lines, 0, 'jobs')
  const jobs = new Map()
  const jobCounts = new Map()
  if (!jobsBlock) return { jobs, jobCounts, lines }
  for (let index = jobsBlock.start + 1; index < jobsBlock.end;) {
    if (indentation(lines[index]) !== 2) {
      index += 1
      continue
    }
    const field = parseField(lines[index])
    if (!field || field.value) {
      index += 1
      continue
    }
    let jobEnd = index + 1
    while (jobEnd < jobsBlock.end && (lines[jobEnd].trim() === '' || indentation(lines[jobEnd]) > 2)) jobEnd += 1
    const stepsBlock = findBlock(lines, 4, 'steps', index + 1, jobEnd)
    const strategyBlock = findBlock(lines, 4, 'strategy', index + 1, jobEnd)
    const matrixBlock = strategyBlock && findBlock(lines, 6, 'matrix', strategyBlock.start + 1, strategyBlock.end)
    const osField = matrixBlock && findBlock(lines, 8, 'os', matrixBlock.start + 1, matrixBlock.end)
    const includeBlock = matrixBlock && findBlock(lines, 8, 'include', matrixBlock.start + 1, matrixBlock.end)
    const defaultsBlock = findBlock(lines, 4, 'defaults', index + 1, jobEnd)
    const defaultsRunBlock = defaultsBlock && findBlock(lines, 6, 'run', defaultsBlock.start + 1, defaultsBlock.end)
    const defaultWorkingDirectoryField = defaultsRunBlock
      && findBlock(lines, 8, 'working-directory', defaultsRunBlock.start + 1, defaultsRunBlock.end)
    const defaultShellField = defaultsRunBlock
      && findBlock(lines, 8, 'shell', defaultsRunBlock.start + 1, defaultsRunBlock.end)
    const runsOnField = findBlock(lines, 4, 'runs-on', index + 1, jobEnd)
    const conditionField = findBlock(lines, 4, 'if', index + 1, jobEnd)
    const continueOnErrorField = findBlock(lines, 4, 'continue-on-error', index + 1, jobEnd)
    const os = osField ? parseInlineSequence(parseField(lines[osField.start])?.value ?? '') : []
    jobCounts.set(field.key, (jobCounts.get(field.key) ?? 0) + 1)
    jobs.set(field.key, {
      steps: stepsBlock ? parseSteps(lines, stepsBlock) : [],
      matrixOs: os,
      matrixInclude: includeBlock ? parseMappingSequence(lines, includeBlock) : [],
      runsOn: runsOnField ? unquote(parseField(lines[runsOnField.start])?.value ?? '') : '',
      condition: conditionField ? unquote(parseField(lines[conditionField.start])?.value ?? '') : '',
      continueOnError: continueOnErrorField
        ? unquote(parseField(lines[continueOnErrorField.start])?.value ?? '')
        : '',
      defaultWorkingDirectory: defaultWorkingDirectoryField
        ? unquote(parseField(lines[defaultWorkingDirectoryField.start])?.value ?? '')
        : '',
      defaultShell: defaultShellField
        ? unquote(parseField(lines[defaultShellField.start])?.value ?? '')
        : '',
    })
    index = jobEnd
  }
  return { jobs, jobCounts, lines }
}

const normalizeExpression = (value) => {
  let normalized = unquote(value).trim()
  if (normalized.startsWith('${{') && normalized.endsWith('}}')) normalized = normalized.slice(3, -2).trim()
  while (normalized.startsWith('(') && normalized.endsWith(')')) normalized = normalized.slice(1, -1).trim()
  return normalized.toLowerCase().replace(/\s+/g, ' ')
}

const isConstantFalse = (value) => new Set(['false', '0', 'null', '~', 'no', 'off']).has(normalizeExpression(value))

const isTargetOsCondition = (value, label) => {
  const normalized = normalizeExpression(value)
  const os = label.toLowerCase()
  return normalized === `runner.os == '${os}'` || normalized === `runner.os == "${os}"`
}

const runsForTarget = (step, label) => {
  const condition = step.fields.if
  return !condition || isTargetOsCondition(condition, label)
}

const validateProtectedStep = (steps, target, stepSpec) => {
  const errors = []
  const name = `${stepSpec.name} (${target.label})`
  const matches = steps.filter((step) => step.fields.name === name)
  if (matches.length !== 1) {
    errors.push(`electron-build must contain exactly one ${name} step, received ${matches.length}`)
    return { errors, step: null }
  }
  const step = matches[0]
  const condition = step.fields.if ?? ''
  if (!condition || isConstantFalse(condition)) errors.push(`${name} has a missing or constant-false if condition`)
  if (!isTargetOsCondition(condition, target.label)) {
    errors.push(`${name} if condition does not select ${target.label}`)
  }
  const workingDirectory = unquote(step.fields['working-directory'] ?? '')
  if (!['electron', './electron', '${{ github.workspace }}/electron'].includes(workingDirectory)) {
    errors.push(`${name} must use the electron working directory`)
  }
  if (step.runLines.length !== 1 || step.runLines[0] !== stepSpec.command) {
    errors.push(`${name} must run exactly: ${stepSpec.command}`)
  }
  return { errors, step }
}

const validateE2EPipeline = (steps, target) => {
  const errors = []
  const protectedSpecs = [
    { key: 'unit', name: 'Run Electron E2E Unit Tests', command: 'npm run test:e2e:unit' },
    { key: 'runtime', name: 'Run Python Runtime Recovery Smoke', command: 'npm run test:runtime-smoke' },
    { key: 'redaction', name: 'Run Electron E2E Redaction Test', command: target.redactionCommand },
    { key: 'e2e', name: 'Run Electron E2E', command: target.e2eCommand },
  ]
  const protectedSteps = new Map()
  for (const stepSpec of protectedSpecs) {
    const validation = validateProtectedStep(steps, target, stepSpec)
    errors.push(...validation.errors)
    if (validation.step) protectedSteps.set(stepSpec.key, validation.step)
  }

  const prerequisiteCommands = ['npm ci', 'npm run install:runtime', 'npm run build']
  const prerequisiteIndices = []
  for (const command of prerequisiteCommands) {
    const prerequisite = steps.find((candidate) => candidate.runLines.length === 1
      && candidate.runLines[0] === command && runsForTarget(candidate, target.label))
    prerequisiteIndices.push(prerequisite?.index ?? Number.POSITIVE_INFINITY)
    const unitStep = protectedSteps.get('unit')
    if (!prerequisite || (unitStep && prerequisite.index >= unitStep.index)) {
      errors.push(`Run Electron E2E Unit Tests (${target.label}) must run after ${command}`)
    }
  }
  const orderedIndices = [
    ...prerequisiteIndices,
    protectedSteps.get('unit')?.index ?? Number.POSITIVE_INFINITY,
    protectedSteps.get('runtime')?.index ?? Number.POSITIVE_INFINITY,
    protectedSteps.get('redaction')?.index ?? Number.POSITIVE_INFINITY,
    protectedSteps.get('e2e')?.index ?? Number.POSITIVE_INFINITY,
  ]
  if (!orderedIndices.every((index, position) => position === 0 || index > orderedIndices[position - 1])) {
    errors.push(`Electron E2E (${target.label}) must preserve npm ci -> install:runtime -> build -> unit -> runtime smoke -> redaction -> default E2E order`)
  }
  return errors
}

const validateNamedCommandStep = (jobName, steps, spec) => {
  const errors = []
  const matches = steps.filter((step) => step.fields.name === spec.name)
  if (matches.length !== 1) {
    errors.push(`${jobName} must contain exactly one ${spec.name} step, received ${matches.length}`)
    return { errors, step: null }
  }
  const step = matches[0]
  const condition = step.fields.if ?? ''
  if (spec.osLabel) {
    if (!condition || isConstantFalse(condition)) errors.push(`${spec.name} has a missing or constant-false if condition`)
    if (!isTargetOsCondition(condition, spec.osLabel)) errors.push(`${spec.name} if condition does not select ${spec.osLabel}`)
  } else if (condition) {
    errors.push(`${spec.name} must run unconditionally for every matrix entry`)
  }
  if (Object.hasOwn(step.fields, 'continue-on-error')) {
    errors.push(`${spec.name} must not set continue-on-error`)
  }
  if (Object.hasOwn(step.fields, 'shell')) {
    errors.push(`${spec.name} must not override the command shell`)
  }
  if (spec.workingDirectories) {
    const workingDirectory = unquote(step.fields['working-directory'] ?? '')
    if (!spec.workingDirectories.includes(workingDirectory)) {
      errors.push(`${spec.name} has an invalid working directory`)
    }
  }
  if (spec.effectiveWorkingDirectories) {
    const override = unquote(step.fields['working-directory'] ?? '')
    const effectiveWorkingDirectory = override || spec.defaultWorkingDirectory
    if (!spec.effectiveWorkingDirectories.includes(effectiveWorkingDirectory)) {
      errors.push(`${spec.name} must run in the python working directory`)
    }
  }
  if (step.runLines.length !== spec.commands.length
    || step.runLines.some((command, index) => command !== spec.commands[index])) {
    errors.push(`${spec.name} must run exactly: ${spec.commands.join(' && ')}`)
  }
  return { errors, step }
}

const validatePlatformChecks = (steps) => {
  const errors = []
  const setupGoMatches = steps.filter((step) => step.fields.uses === 'actions/setup-go@v6')
  let setupGo = null
  if (setupGoMatches.length !== 1) {
    errors.push(`electron-build must contain exactly one actions/setup-go@v6 step, received ${setupGoMatches.length}`)
  } else {
    setupGo = setupGoMatches[0]
    const condition = setupGo.fields.if ?? ''
    if (!condition || isConstantFalse(condition)) errors.push('actions/setup-go@v6 has a missing or constant-false if condition')
    if (!isTargetOsCondition(condition, 'Windows')) errors.push('actions/setup-go@v6 if condition does not select Windows')
  }

  const launcher = validateNamedCommandStep('electron-build', steps, {
    name: 'Test Windows launcher',
    osLabel: 'Windows',
    workingDirectories: ['tools/yuizaki-launcher', './tools/yuizaki-launcher', '${{ github.workspace }}/tools/yuizaki-launcher'],
    commands: ['go test ./...'],
  })
  const linuxLibraries = validateNamedCommandStep('electron-build', steps, {
    name: 'Install Linux GUI runtime libraries',
    osLabel: 'Linux',
    workingDirectories: ['.', './', '${{ github.workspace }}'],
    commands: [
      'sudo apt-get update',
      'sudo apt-get install -y libxtst6 xvfb xauth',
      'sudo chown root electron/node_modules/electron/dist/chrome-sandbox',
      'sudo chmod 4755 electron/node_modules/electron/dist/chrome-sandbox',
    ],
  })
  errors.push(...launcher.errors, ...linuxLibraries.errors)

  const windowsE2E = steps.find((step) => step.fields.name === 'Run Electron E2E (Windows)')
  const linuxE2E = steps.find((step) => step.fields.name === 'Run Electron E2E (Linux)')
  if (windowsE2E && setupGo && launcher.step
    && !(windowsE2E.index < setupGo.index && setupGo.index < launcher.step.index)) {
    errors.push('Windows platform checks must preserve default E2E -> setup-go -> launcher test order')
  }
  if (linuxLibraries.step && linuxE2E && !(linuxLibraries.step.index < linuxE2E.index)) {
    errors.push('Linux platform checks must preserve library install -> default E2E order')
  }
  return errors
}

const expectedPythonMatrix = [
  { os: 'ubuntu-latest', 'python-version': '3.11', 'requirements-lock': 'requirements-dev-lock-linux.txt' },
  { os: 'ubuntu-latest', 'python-version': '3.12', 'requirements-lock': 'requirements-dev-lock-linux.txt' },
  { os: 'ubuntu-latest', 'python-version': '3.13', 'requirements-lock': 'requirements-dev-lock-linux.txt' },
  { os: 'windows-latest', 'python-version': '3.11', 'requirements-lock': 'requirements-dev-lock-windows.txt' },
]

const matrixSignature = (entry) => JSON.stringify(Object.fromEntries(Object.entries(entry).sort(([left], [right]) => left.localeCompare(right))))

const validatePythonJob = (job) => {
  const errors = []
  if (job.defaultWorkingDirectory !== 'python') {
    errors.push('python-test defaults.run.working-directory must be python')
  }
  const actualMatrix = job.matrixInclude.map(matrixSignature).sort()
  const expectedMatrix = expectedPythonMatrix.map(matrixSignature).sort()
  if (actualMatrix.length !== expectedMatrix.length
    || actualMatrix.some((entry, index) => entry !== expectedMatrix[index])) {
    errors.push('python-test matrix.include must exactly match the protected OS, Python version, and lock combinations')
  }
  const pythonStepSpecs = [
    {
      key: 'install',
      name: 'Install dependencies',
      commands: [
        'python -m pip install --upgrade pip',
        'pip install -r ${{ matrix.requirements-lock }}',
        'pip check',
        'python scripts/check_installed_lock.py --lock ${{ matrix.requirements-lock }}',
      ],
    },
    { key: 'ruff', name: 'Check Python runtime errors with ruff', commands: ['ruff check . --select E9,F63,F7,F82'] },
    { key: 'pyright', name: 'Type check with pyright', commands: ['pyright --pythonversion ${{ matrix.python-version }}'] },
    { key: 'pytest', name: 'Run tests', commands: ['pytest . -q --tb=short'] },
  ]
  const protectedSteps = new Map()
  for (const spec of pythonStepSpecs) {
    const validation = validateNamedCommandStep('python-test', job.steps, {
      ...spec,
      defaultWorkingDirectory: job.defaultWorkingDirectory,
      effectiveWorkingDirectories: ['python', './python', '${{ github.workspace }}/python'],
    })
    errors.push(...validation.errors)
    if (validation.step) protectedSteps.set(spec.key, validation.step)
  }
  const orderedIndices = pythonStepSpecs.map((spec) => protectedSteps.get(spec.key)?.index ?? Number.POSITIVE_INFINITY)
  if (!orderedIndices.every((index, position) => position === 0 || index > orderedIndices[position - 1])) {
    errors.push('python-test must preserve Install dependencies -> ruff -> pyright -> pytest order')
  }
  return errors
}

const validateQdrantIntegrationJob = (job) => {
  const errors = []
  if (job.runsOn !== 'ubuntu-latest') {
    errors.push('qdrant-integration runs-on must be ubuntu-latest')
  }
  if (job.condition) errors.push('qdrant-integration must run unconditionally')
  if (job.continueOnError) errors.push('qdrant-integration must not set continue-on-error')
  if (job.defaultShell) errors.push('qdrant-integration must not override defaults.run.shell')
  const checkoutSteps = job.steps.filter((step) => step.fields.uses === 'actions/checkout@v4')
  if (checkoutSteps.length !== 1) {
    errors.push(`qdrant-integration must contain exactly one actions/checkout@v4 step, received ${checkoutSteps.length}`)
  } else if (checkoutSteps[0].fields.if || Object.hasOwn(checkoutSteps[0].fields, 'continue-on-error')) {
    errors.push('qdrant-integration actions/checkout@v4 must run unconditionally without continue-on-error')
  }
  const setupPythonSteps = job.steps.filter((step) => step.fields.uses === 'actions/setup-python@v5')
  if (setupPythonSteps.length !== 1) {
    errors.push(`qdrant-integration must contain exactly one actions/setup-python@v5 step, received ${setupPythonSteps.length}`)
  } else {
    const setupPython = setupPythonSteps[0]
    if (setupPython.fields.if || Object.hasOwn(setupPython.fields, 'continue-on-error')) {
      errors.push('qdrant-integration actions/setup-python@v5 must run unconditionally without continue-on-error')
    }
    const expectedWith = {
      'python-version': '3.12',
      cache: 'pip',
      'cache-dependency-path': 'python/requirements-dev-lock-linux.txt',
    }
    if (Object.keys(setupPython.withFields).length !== Object.keys(expectedWith).length
      || Object.entries(expectedWith).some(([key, value]) => setupPython.withFields[key] !== value)) {
      errors.push('qdrant-integration actions/setup-python@v5 must pin Python 3.12 and the Linux dependency cache')
    }
  }
  const install = validateNamedCommandStep('qdrant-integration', job.steps, {
    name: 'Install Qdrant integration dependencies',
    effectiveWorkingDirectories: ['python', './python', '${{ github.workspace }}/python'],
    defaultWorkingDirectory: job.defaultWorkingDirectory,
    commands: [
      'python -m pip install --upgrade pip',
      'pip install -r requirements-dev-lock-linux.txt',
      'pip check',
      'python scripts/check_installed_lock.py --lock requirements-dev-lock-linux.txt',
    ],
  })
  const integration = validateNamedCommandStep('qdrant-integration', job.steps, {
    name: 'Run real Qdrant recovery integration',
    effectiveWorkingDirectories: ['', '.', './', '${{ github.workspace }}'],
    defaultWorkingDirectory: job.defaultWorkingDirectory,
    commands: ['python scripts/run_qdrant_integration.py'],
  })
  errors.push(...install.errors, ...integration.errors)
  if (install.step && integration.step && install.step.index >= integration.step.index) {
    errors.push('qdrant-integration must preserve dependency install -> real integration order')
  }
  return errors
}

export const validateProtectedCi = (text) => {
  const errors = []
  const workflow = parseWorkflow(text)
  for (const fragment of requiredFragments) {
    if (!text.includes(fragment)) errors.push(`missing required CI fragment: ${fragment}`)
  }
  for (const markers of orderedMarkers) {
    for (const marker of markers) {
      if (count(text, marker) !== 1) errors.push(`CI marker must occur exactly once: ${marker}`)
    }
    const positions = markers.map((marker) => text.indexOf(marker))
    if (positions.some((position) => position < 0) || positions.some((position, index) => index > 0 && position <= positions[index - 1])) {
      errors.push(`CI anchors are missing or out of order: ${markers.join(' -> ')}`)
    }
  }
  const electronJob = workflow.jobs.get('electron-build')
  if (!electronJob) {
    errors.push('missing jobs.electron-build')
  } else {
    for (const os of ['windows-latest', 'ubuntu-latest']) {
      if (!electronJob.matrixOs.includes(os)) errors.push(`electron-build matrix.os is missing ${os}`)
    }
    errors.push(...validateE2EPipeline(electronJob.steps, {
      label: 'Windows',
      redactionCommand: 'npm run test:e2e:redaction',
      e2eCommand: 'npm run test:e2e',
    }))
    errors.push(...validateE2EPipeline(electronJob.steps, {
      label: 'Linux',
      redactionCommand: 'xvfb-run -a npm run test:e2e:redaction',
      e2eCommand: 'xvfb-run -a npm run test:e2e',
    }))
    errors.push(...validatePlatformChecks(electronJob.steps))
  }
  const pythonJob = workflow.jobs.get('python-test')
  if (!pythonJob) errors.push('missing jobs.python-test')
  else errors.push(...validatePythonJob(pythonJob))
  const qdrantIntegrationJob = workflow.jobs.get('qdrant-integration')
  if ((workflow.jobCounts.get('qdrant-integration') ?? 0) !== 1) {
    errors.push(`jobs.qdrant-integration must occur exactly once, received ${workflow.jobCounts.get('qdrant-integration') ?? 0}`)
  }
  if (!qdrantIntegrationJob) errors.push('missing jobs.qdrant-integration')
  else errors.push(...validateQdrantIntegrationJob(qdrantIntegrationJob))
  return errors
}

export const verifyProtectedCiFile = (file) => {
  const text = fs.readFileSync(file, 'utf8')
  const errors = validateProtectedCi(text)
  if (errors.length > 0) throw new Error(errors.join('\n'))
  return {
    file,
    bytes: Buffer.byteLength(text),
    checks: requiredFragments.length + orderedMarkers.length + structuredContractCount,
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const file = path.resolve(repositoryRoot, process.argv[2] || '.github/workflows/ci.yml')
  const result = verifyProtectedCiFile(file)
  console.log(`Protected CI contract passed: ${result.checks} checks, ${result.bytes} bytes`)
}
