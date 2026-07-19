import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { pythonVenvCandidates, resolvePythonRuntime } from '../python-runtime'

describe('python runtime resolution', () => {
  it('uses the Windows virtual environment layout', () => {
    const root = path.resolve('C:/yuizaki/python')
    const expected = path.join(root, '.venv', 'Scripts', 'python.exe')
    expect(pythonVenvCandidates(root, 'win32')).toEqual([expected])
    expect(resolvePythonRuntime(root, 'win32', (candidate) => candidate === expected)).toEqual({
      executable: expected,
      venvPath: expected,
      venvExists: true,
    })
  })

  it('uses the POSIX virtual environment layout on Linux', () => {
    const root = '/opt/yuizaki/python'
    const expected = path.join(root, '.venv', 'bin', 'python')
    expect(pythonVenvCandidates(root, 'linux')[0]).toBe(expected)
    expect(resolvePythonRuntime(root, 'linux', (candidate) => candidate === expected)).toEqual({
      executable: expected,
      venvPath: expected,
      venvExists: true,
    })
  })

  it('falls back to the platform interpreter when the venv is absent', () => {
    expect(resolvePythonRuntime('/tmp/python', 'linux', () => false).executable).toBe('python3')
    expect(resolvePythonRuntime('C:/python', 'win32', () => false).executable).toBe('python')
  })
})
