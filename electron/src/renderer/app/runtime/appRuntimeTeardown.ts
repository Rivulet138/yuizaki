export interface AppRuntimeTeardownDependencies {
  stop: () => void | Promise<void>
  disconnect: () => void | Promise<void>
}

export const createAppRuntimeTeardown = ({ stop, disconnect }: AppRuntimeTeardownDependencies) => {
  let teardownPromise: Promise<void> | null = null

  const run = (): Promise<void> => {
    if (teardownPromise) return teardownPromise
    teardownPromise = (async () => {
      await stop()
      await disconnect()
    })()
    return teardownPromise
  }

  return { run }
}
