import type { AvatarManifest } from '../../shared/pet-control'

const FALLBACK_MOTION_GROUPS = ['Idle', 'Tap', 'Tap@Body', 'Flick', 'Flick@Body'] as const

/**
 * Resolve the actual motion groups declared by the active model instead of
 * probing a hard-coded list that may not exist in the bundled asset.
 */
export const resolveLive2DMotionGroups = (
  manifest: AvatarManifest | null | undefined,
): string[] => {
  const groups = Object.values(manifest?.motions ?? {})
    .map((motion) => motion.group?.trim())
    .filter((group): group is string => Boolean(group))
  const unique = [...new Set(groups)]
  return unique.length > 0 ? unique : [...FALLBACK_MOTION_GROUPS]
}
