import type { Transform } from 'node:stream'

export type E2ERedactor = {
  redactText: (input: unknown) => string
  redactValue: (value: unknown) => unknown
  stringify: (value: unknown, space?: number) => string
}

export function createE2ERedactor(rawToken: string | string[]): E2ERedactor
export function createRedactingTransform(redactor: E2ERedactor): Transform
