import type {
  AvatarManifest,
  PetControlDirective,
  PetControlValidation,
  PetControlValidationResult,
  PetExpressionMixItem,
  PetMotionTarget,
  PetParameterOverrideItem,
} from './pet-control'

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value))

const neutralExpression = (manifest: AvatarManifest): string | undefined =>
  manifest.expressions.find((item) => /neutral|idle|normal|默认|普通/.test(item.id.toLowerCase()))?.id
  ?? manifest.expressions[0]?.id

const baseValidation = (): PetControlValidation => ({
  valid: true,
  errors: [],
  warnings: [],
})

export const validateExpressionMix = (
  mix: PetExpressionMixItem[],
  manifest: AvatarManifest,
): PetControlValidationResult => {
  const validation = baseValidation()
  const expressionIds = new Set(manifest.expressions.map((item) => item.id))
  const expressionAliases = new Map<string, string>()
  for (const expression of manifest.expressions) {
    for (const alias of expression.aliases ?? []) {
      expressionAliases.set(alias, expression.id)
    }
  }

  const normalizedMix: PetExpressionMixItem[] = []
  for (const item of mix) {
    const resolved = expressionIds.has(item.expression)
      ? item.expression
      : expressionAliases.get(item.expression)
    if (!resolved) {
      validation.valid = false
      validation.errors.push(`Unknown expression: ${item.expression}`)
      continue
    }
    const rawWeight = item.weight ?? 1
    const weight = clamp(rawWeight, 0, 1)
    if (weight !== rawWeight) {
      validation.warnings.push(`Expression weight clamped for ${resolved}`)
    }
    normalizedMix.push({ expression: resolved, weight })
  }

  if (normalizedMix.length === 0) {
    const fallback = neutralExpression(manifest)
    if (fallback) {
      validation.fallbackExpression = fallback
      normalizedMix.push({ expression: fallback, weight: 1 })
    }
  }

  return {
    ...validation,
    directive: {
      expressionMix: normalizedMix,
      parameterOverrides: [],
      intensity: 1,
      durationMs: 1800,
    },
  }
}

export const validateParameterOverrides = (
  overrides: PetParameterOverrideItem[],
  manifest: AvatarManifest,
): PetControlValidationResult => {
  const validation = baseValidation()
  const parameterRanges = new Map(manifest.parameterControls.map((item) => [item.id, item]))
  const normalizedOverrides: PetParameterOverrideItem[] = []

  for (const item of overrides) {
    const parameter = parameterRanges.get(item.id)
    if (!parameter) {
      validation.valid = false
      validation.errors.push(`Unknown parameter: ${item.id}`)
      continue
    }
    const value = clamp(item.value, parameter.min, parameter.max)
    if (value !== item.value) {
      validation.warnings.push(`Parameter value clamped for ${item.id}`)
    }
    const rawWeight = item.weight ?? 1
    const weight = clamp(rawWeight, 0, 1)
    if (weight !== rawWeight) {
      validation.warnings.push(`Parameter weight clamped for ${item.id}`)
    }
    normalizedOverrides.push({ id: item.id, value, weight })
  }

  return {
    ...validation,
    directive: {
      expressionMix: [],
      parameterOverrides: normalizedOverrides,
      intensity: 1,
      durationMs: 1800,
    },
  }
}

export const validateMotionTarget = (
  motion: PetMotionTarget | undefined,
  manifest: AvatarManifest,
): PetControlValidationResult => {
  const validation = baseValidation()
  let normalizedMotion: PetMotionTarget | undefined

  if (motion) {
    const groupMotions = Object.entries(manifest.motions).filter(([key, item]) =>
      key === motion.group || item.group === motion.group || item.file === motion.group,
    )
    if (
      Number.isInteger(motion.index)
      && motion.index >= 0
      && motion.index < groupMotions.length
    ) {
      normalizedMotion = { group: motion.group, index: motion.index }
    } else {
      validation.valid = false
      validation.errors.push(`Unknown motion target: ${motion.group}:${motion.index}`)
    }
  }

  return {
    ...validation,
    directive: {
      expressionMix: [],
      parameterOverrides: [],
      ...(normalizedMotion ? { motion: normalizedMotion } : {}),
      intensity: 1,
      durationMs: 1800,
    },
  }
}

export const validatePetControlDirective = (
  directive: Partial<PetControlDirective>,
  manifest: AvatarManifest,
): PetControlValidationResult => {
  const expressionValidation = validateExpressionMix(directive.expressionMix ?? [], manifest)
  const parameterValidation = validateParameterOverrides(directive.parameterOverrides ?? [], manifest)
  const motionValidation = validateMotionTarget(directive.motion, manifest)
  const rawIntensity = directive.intensity ?? 1
  const intensity = clamp(rawIntensity, 0, 1)
  const rawDurationMs = directive.durationMs ?? 1800
  const durationMs = Math.round(clamp(rawDurationMs, 100, 10000))
  const warnings = [
    ...expressionValidation.warnings,
    ...parameterValidation.warnings,
    ...motionValidation.warnings,
  ]

  if (intensity !== rawIntensity) {
    warnings.push('Intensity clamped')
  }
  if (durationMs !== rawDurationMs) {
    warnings.push('Duration clamped')
  }

  const result: PetControlValidationResult = {
    valid: expressionValidation.valid && parameterValidation.valid && motionValidation.valid,
    errors: [
      ...expressionValidation.errors,
      ...parameterValidation.errors,
      ...motionValidation.errors,
    ],
    warnings,
    directive: {
      expressionMix: expressionValidation.directive.expressionMix,
      parameterOverrides: parameterValidation.directive.parameterOverrides,
      ...(motionValidation.directive.motion ? { motion: motionValidation.directive.motion } : {}),
      intensity,
      durationMs,
    },
  }
  if (expressionValidation.fallbackExpression) {
    result.fallbackExpression = expressionValidation.fallbackExpression
  }
  return result
}
