type LogLevel = 'info' | 'warn' | 'error'

interface StructuredLogEntry {
  timestamp: string
  level: LogLevel
  event: string
  traceId?: string
  pluginId?: string
  routeId?: string
  invocationId?: string
  detail?: unknown
}

const emit = (entry: StructuredLogEntry) => {
  const line = JSON.stringify(entry)
  if (entry.level === 'error') {
    console.error(line)
    return
  }
  if (entry.level === 'warn') {
    console.warn(line)
    return
  }
  console.info(line)
}

export const logger = {
  info: (...args: unknown[]) => console.info(...args),
  warn: (...args: unknown[]) => console.warn(...args),
  error: (...args: unknown[]) => console.error(...args),
  structured: (entry: Omit<StructuredLogEntry, 'timestamp'>) => {
    emit({
      ...entry,
      timestamp: new Date().toISOString(),
    })
  },
}
