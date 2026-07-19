export interface Live2DCoreModel {
  getParameterValueById(parameterId: string): number
  setParameterValueById(parameterId: string, value: number, weight?: number): void
}

export const isObjectRecord = (value: unknown): value is Record<PropertyKey, unknown> =>
  typeof value === 'object' && value !== null

const hasFunction = <TName extends string>(
  value: Record<PropertyKey, unknown>,
  name: TName,
): value is Record<PropertyKey, unknown> & Record<TName, (...args: never[]) => unknown> =>
  typeof value[name] === 'function'

export const isLive2DCoreModel = (value: unknown): value is Live2DCoreModel => {
  if (!isObjectRecord(value)) {
    return false
  }

  return hasFunction(value, 'getParameterValueById') && hasFunction(value, 'setParameterValueById')
}

export const resolveLive2DCoreModel = (model: unknown): Live2DCoreModel | null => {
  if (!isObjectRecord(model)) {
    return null
  }

  const live2dModel = model._model
  if (!isObjectRecord(live2dModel)) {
    return null
  }

  const coreModel = live2dModel._model
  return isLive2DCoreModel(coreModel) ? coreModel : null
}
