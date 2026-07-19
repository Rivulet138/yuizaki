export interface RuntimeExceptionRecord {
  timestamp: string
  type: string
  detail: string
}

const runtimeExceptions: RuntimeExceptionRecord[] = []

export const recordRuntimeException = (type: string, error: unknown): void => {
  runtimeExceptions.unshift({
    timestamp: new Date().toISOString(),
    type,
    detail: error instanceof Error ? error.stack || error.message : String(error),
  })
  if (runtimeExceptions.length > 50) {
    runtimeExceptions.length = 50
  }
}

export const getRuntimeExceptions = (): RuntimeExceptionRecord[] => [...runtimeExceptions]
