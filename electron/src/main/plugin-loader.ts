import fs from 'fs'
import path from 'path'
import {
  PLUGIN_MANIFEST_VERSION,
  type DesktopPetPluginManifest,
  type PluginExecutionPolicy,
  type PluginLoadFailure,
  type PluginManifestValidationIssue,
  type PluginModelProviderContribution,
  type PluginPermissionManifest,
  type PluginPetEventSubscription,
  type PluginRouteContribution,
  type PluginToolCapabilityContribution,
} from '../shared/plugin'
import { PluginRegistry } from './plugin-registry'

const PLUGIN_DIR_CANDIDATES = [path.resolve(__dirname, '../../plugins'), path.resolve(process.cwd(), 'plugins')]
const ROUTE_NAMESPACES = new Set(['pet', 'model', 'system', 'workbench', 'plugin'])
const PET_EVENT_NAMES = new Set([
  'onPetClicked',
  'onPetDragged',
  'onPetIdle',
  'onEmotionChanged',
  'onSpeechStart',
  'onSpeechEnd',
  'onToolStart',
  'onToolEnd',
  'requestPetAction',
])
const PLUGIN_MANIFEST_FIELDS = new Set([
  'manifestVersion',
  'id',
  'name',
  'version',
  'permissions',
  'execution',
  'routes',
  'modelProviders',
  'toolCapabilities',
  'petEvents',
])

const isStringArray = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === 'string')

const isPathInside = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(baseDir, targetPath)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

const resolveRealPluginPath = (inputPath: string): string | null => {
  try {
    return fs.realpathSync.native(inputPath)
  } catch {
    return null
  }
}

const clampExecutionPolicy = (value: unknown): PluginExecutionPolicy => {
  const input = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const rawTimeout = typeof input['maxExecutionTimeMs'] === 'number' ? input['maxExecutionTimeMs'] : 10_000
  const rawConcurrency = typeof input['maxConcurrentExecutions'] === 'number' ? input['maxConcurrentExecutions'] : 1
  const allowCancellation = typeof input['allowCancellation'] === 'boolean' ? input['allowCancellation'] : true

  return {
    maxExecutionTimeMs: Math.max(100, Math.min(60_000, Math.trunc(rawTimeout))),
    maxConcurrentExecutions: Math.max(1, Math.min(10, Math.trunc(rawConcurrency))),
    allowCancellation,
  }
}

const normalizePermissions = (value: unknown): PluginPermissionManifest | null => {
  if (!value || typeof value !== 'object') {
    return null
  }

  const permissions = value as Record<string, unknown>
  const routes = permissions['routes']
  const toolScopes = permissions['toolScopes']
  const modelScopes = permissions['modelScopes']
  const agentBridge = permissions['agentBridge']
  const allowedHosts = permissions['allowedHosts']
  const allowedPaths = permissions['allowedPaths']
  const allowedCommands = permissions['allowedCommands']

  if (!isStringArray(routes) || !isStringArray(toolScopes) || !isStringArray(modelScopes)) {
    return null
  }

  if (agentBridge != null && typeof agentBridge !== 'boolean') {
    return null
  }

  if (
    (allowedHosts != null && !isStringArray(allowedHosts)) ||
    (allowedPaths != null && !isStringArray(allowedPaths)) ||
    (allowedCommands != null && !isStringArray(allowedCommands))
  ) {
    return null
  }

  const normalized = {
    routes: [...routes],
    toolScopes: [...toolScopes],
    modelScopes: [...modelScopes],
  }

  if (agentBridge === true) {
    Object.assign(normalized, { agentBridge: true })
  }

  if (isStringArray(allowedHosts)) {
    Object.assign(normalized, { allowedHosts: [...allowedHosts] })
  }

  if (isStringArray(allowedPaths)) {
    Object.assign(normalized, { allowedPaths: [...allowedPaths] })
  }

  if (isStringArray(allowedCommands)) {
    Object.assign(normalized, { allowedCommands: [...allowedCommands] })
  }

  return normalized
}

const buildLoadFailure = (
  manifestPath: string,
  reason: string,
  validationIssues: PluginManifestValidationIssue[],
  pluginId?: string,
): PluginLoadFailure => {
  const failure: PluginLoadFailure = {
    manifestPath,
    reason,
    validationIssues,
    occurredAt: new Date().toISOString(),
  }
  if (pluginId) {
    failure.pluginId = pluginId
  }
  return failure
}

const validateManifest = (value: unknown, manifestPath: string): {
  plugin: DesktopPetPluginManifest | null
  issues: PluginManifestValidationIssue[]
  pluginId?: string
} => {
  const issues: PluginManifestValidationIssue[] = []

  if (!value || typeof value !== 'object') {
    issues.push({ field: 'manifest', message: 'Plugin manifest must be an object', severity: 'error' })
    return { plugin: null, issues }
  }

  const manifest = value as Record<string, unknown>
  const pluginId = typeof manifest['id'] === 'string' ? manifest['id'] : undefined

  for (const field of Object.keys(manifest)) {
    if (!PLUGIN_MANIFEST_FIELDS.has(field)) {
      issues.push({ field, message: `Unknown plugin manifest field: ${field}`, severity: 'error' })
    }
  }

  if (manifest['manifestVersion'] !== PLUGIN_MANIFEST_VERSION) {
    issues.push({
      field: 'manifestVersion',
      message: `Plugin manifestVersion must be ${PLUGIN_MANIFEST_VERSION}`,
      severity: 'error',
    })
  }

  if (typeof manifest['id'] !== 'string' || manifest['id'].trim().length === 0) {
    issues.push({ field: 'id', message: 'Plugin id is required', severity: 'error' })
  }

  if (typeof manifest['name'] !== 'string' || manifest['name'].trim().length === 0) {
    issues.push({ field: 'name', message: 'Plugin name is required', severity: 'error' })
  }

  const permissions = normalizePermissions(manifest['permissions'])
  if (!permissions) {
    issues.push({
      field: 'permissions',
      message: 'Plugin permissions are required and must declare routes/toolScopes/modelScopes arrays',
      severity: 'error',
    })
  }

  const routesInput = Array.isArray(manifest['routes']) ? manifest['routes'] : []
  const routes = routesInput.flatMap((route, index) => {
    if (!route || typeof route !== 'object') {
      issues.push({ field: `routes[${index}]`, message: 'Route contribution must be an object', severity: 'error' })
      return []
    }

    const candidate = route as Record<string, unknown>
    const id = candidate['id']
    const namespace = candidate['namespace']
    const handler = candidate['handler']
    if (typeof id !== 'string' || typeof namespace !== 'string' || typeof handler !== 'string') {
      issues.push({
        field: `routes[${index}]`,
        message: 'Route contribution requires id, namespace, and handler',
        severity: 'error',
      })
      return []
    }
    if (!ROUTE_NAMESPACES.has(namespace)) {
      issues.push({
        field: `routes[${index}].namespace`,
        message: 'Route contribution namespace is invalid',
        severity: 'error',
      })
      return []
    }

    const pluginDir = path.dirname(manifestPath)
    const handlerPath = path.resolve(pluginDir, handler)
    if (!isPathInside(pluginDir, handlerPath)) {
      issues.push({
        field: `routes[${index}].handler`,
        message: 'Route handler must stay within the plugin directory',
        severity: 'error',
      })
      return []
    }

    const realPluginDir = resolveRealPluginPath(pluginDir)
    const realHandlerPath = resolveRealPluginPath(handlerPath)
    if (!realHandlerPath) {
      issues.push({
        field: `routes[${index}].handler`,
        message: 'Route handler file must exist',
        severity: 'error',
      })
      return []
    }
    if (!realPluginDir || !isPathInside(realPluginDir, realHandlerPath)) {
      issues.push({
        field: `routes[${index}].handler`,
        message: 'Route handler must stay within the real plugin directory',
        severity: 'error',
      })
      return []
    }

    const routeContribution: PluginRouteContribution = {
      id,
      namespace: namespace as 'pet' | 'model' | 'system' | 'workbench' | 'plugin',
      handler: realHandlerPath,
    }
    if (typeof candidate['path'] === 'string') {
      routeContribution.path = candidate['path']
    }
    return [routeContribution]
  })

  const routeIds = new Set<string>()
  for (const route of routes) {
    if (routeIds.has(route.id)) {
      issues.push({ field: 'routes', message: `Duplicate route id: ${route.id}`, severity: 'error' })
    }
    routeIds.add(route.id)
  }

  const modelProviders = Array.isArray(manifest['modelProviders'])
    ? manifest['modelProviders'].flatMap((provider, index) => {
        if (!provider || typeof provider !== 'object') {
          issues.push({ field: `modelProviders[${index}]`, message: 'Model provider must be an object', severity: 'error' })
          return []
        }

        const candidate = provider as Record<string, unknown>
        if (
          typeof candidate['id'] !== 'string' ||
          (candidate['modelType'] !== 'live2d' && candidate['modelType'] !== 'vrm') ||
          typeof candidate['name'] !== 'string'
        ) {
          issues.push({
            field: `modelProviders[${index}]`,
            message: 'Model provider requires id, modelType, and name',
            severity: 'error',
          })
          return []
        }

        const providerContribution: PluginModelProviderContribution = {
          id: candidate['id'],
          modelType: candidate['modelType'] as 'live2d' | 'vrm',
          name: candidate['name'],
        }
        if (typeof candidate['assetPath'] === 'string') {
          providerContribution.assetPath = candidate['assetPath']
        }
        return [providerContribution]
      })
    : []

  const toolCapabilities = Array.isArray(manifest['toolCapabilities'])
    ? manifest['toolCapabilities'].flatMap((tool, index) => {
        if (!tool || typeof tool !== 'object') {
          issues.push({ field: `toolCapabilities[${index}]`, message: 'Tool capability must be an object', severity: 'error' })
          return []
        }

        const candidate = tool as Record<string, unknown>
        if (typeof candidate['id'] !== 'string' || typeof candidate['name'] !== 'string' || typeof candidate['desc'] !== 'string') {
          issues.push({
            field: `toolCapabilities[${index}]`,
            message: 'Tool capability requires id, name, and desc',
            severity: 'error',
          })
          return []
        }

        const capabilityContribution: PluginToolCapabilityContribution = {
          id: candidate['id'],
          name: candidate['name'],
          desc: candidate['desc'],
        }
        if (
          candidate['riskLevel'] === 'safe' ||
          candidate['riskLevel'] === 'low' ||
          candidate['riskLevel'] === 'medium' ||
          candidate['riskLevel'] === 'high' ||
          candidate['riskLevel'] === 'critical'
        ) {
          capabilityContribution.riskLevel = candidate['riskLevel']
        }
        if (Array.isArray(candidate['scopes'])) {
          capabilityContribution.scopes = candidate['scopes'].filter((item): item is string => typeof item === 'string')
        }
        if (Array.isArray(candidate['tags'])) {
          capabilityContribution.tags = candidate['tags'].filter((item): item is string => typeof item === 'string')
        }

        return [capabilityContribution]
      })
    : []

  const petEvents = Array.isArray(manifest['petEvents'])
    ? manifest['petEvents'].flatMap((event, index) => {
        if (!event || typeof event !== 'object') {
          issues.push({ field: `petEvents[${index}]`, message: 'Pet event subscription must be an object', severity: 'error' })
          return []
        }

        const candidate = event as Record<string, unknown>
        if (typeof candidate['event'] !== 'string' || !PET_EVENT_NAMES.has(candidate['event'])) {
          issues.push({
            field: `petEvents[${index}].event`,
            message: 'Pet event subscription uses an unsupported event name',
            severity: 'error',
          })
          return []
        }

        const subscription: PluginPetEventSubscription = {
          event: candidate['event'] as PluginPetEventSubscription['event'],
        }
        if (typeof candidate['routeId'] === 'string') {
          subscription.routeId = candidate['routeId']
        }
        if (typeof candidate['description'] === 'string') {
          subscription.description = candidate['description'].trim().slice(0, 160)
        }
        return [subscription]
      })
    : []

  if (permissions) {
    for (const routeId of permissions.routes) {
      if (!routeIds.has(routeId)) {
        issues.push({ field: 'permissions.routes', message: `Unknown route permission target: ${routeId}`, severity: 'error' })
      }
    }
    for (const route of routes) {
      if (!permissions.routes.includes(route.id)) {
        issues.push({ field: 'permissions.routes', message: `Route contribution is not permitted: ${route.id}`, severity: 'error' })
      }
    }

    const toolIds = new Set(toolCapabilities.map((tool) => tool.id))
    for (const toolId of permissions.toolScopes) {
      if (!toolIds.has(toolId)) {
        issues.push({ field: 'permissions.toolScopes', message: `Unknown tool permission target: ${toolId}`, severity: 'error' })
      }
    }

    const providerIds = new Set(modelProviders.map((provider) => provider.id))
    for (const providerId of permissions.modelScopes) {
      if (!providerIds.has(providerId)) {
        issues.push({ field: 'permissions.modelScopes', message: `Unknown model permission target: ${providerId}`, severity: 'error' })
      }
    }

    for (const subscription of petEvents) {
      if (subscription.routeId && !routeIds.has(subscription.routeId)) {
        issues.push({ field: 'petEvents.routeId', message: `Unknown pet event route target: ${subscription.routeId}`, severity: 'error' })
      }
      if (subscription.routeId && !permissions.routes.includes(subscription.routeId)) {
        issues.push({ field: 'permissions.routes', message: `Pet event route is not permitted: ${subscription.routeId}`, severity: 'error' })
      }
    }
  }

  if (issues.some((issue) => issue.severity === 'error') || !permissions || typeof manifest['id'] !== 'string' || typeof manifest['name'] !== 'string') {
    const result: { plugin: DesktopPetPluginManifest | null; issues: PluginManifestValidationIssue[]; pluginId?: string } = {
      plugin: null,
      issues,
    }
    if (pluginId) {
      result.pluginId = pluginId
    }
    return result
  }

  const plugin: DesktopPetPluginManifest = {
    manifestVersion: PLUGIN_MANIFEST_VERSION,
    id: manifest['id'],
    name: manifest['name'],
    manifestPath,
    permissions,
    execution: clampExecutionPolicy(manifest['execution']),
    routes,
    modelProviders,
    toolCapabilities,
    petEvents,
  }
  if (typeof manifest['version'] === 'string') {
    plugin.version = manifest['version']
  }

  const result: { plugin: DesktopPetPluginManifest | null; issues: PluginManifestValidationIssue[]; pluginId?: string } = {
    plugin,
    issues,
  }
  if (pluginId) {
    result.pluginId = pluginId
  }
  return result
}

export const resolvePluginRootDir = (): string | null => PLUGIN_DIR_CANDIDATES.find((candidate) => fs.existsSync(candidate)) ?? null

export const loadPluginsFromDisk = (registry: PluginRegistry, pluginRootOverride?: string): DesktopPetPluginManifest[] => {
  const pluginRoot = pluginRootOverride ?? resolvePluginRootDir()
  if (!pluginRoot) {
    return []
  }

  const entries = fs.readdirSync(pluginRoot, { withFileTypes: true })
  const loaded: DesktopPetPluginManifest[] = []

  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue
    }

    const manifestPath = path.join(pluginRoot, entry.name, 'plugin.json')
    if (!fs.existsSync(manifestPath)) {
      continue
    }

    try {
      const raw = fs.readFileSync(manifestPath, 'utf8')
      const parsed = JSON.parse(raw) as unknown
      const result = validateManifest(parsed, manifestPath)

      if (!result.plugin) {
        registry.recordLoadFailure(buildLoadFailure(manifestPath, 'Plugin manifest validation failed', result.issues, result.pluginId))
        continue
      }

      registry.register(result.plugin, result.issues)
      loaded.push(result.plugin)
    } catch (error) {
      registry.recordLoadFailure(
        buildLoadFailure(
          manifestPath,
          error instanceof Error ? error.message : 'Failed to parse plugin manifest',
          [
            {
              field: 'manifest',
              message: error instanceof Error ? error.message : 'Failed to parse plugin manifest',
              severity: 'error',
            },
          ],
        ),
      )
    }
  }

  return loaded
}
