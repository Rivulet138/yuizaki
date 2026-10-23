import { t } from './index'

/**
 * Resolves desktop-pet event copy from `shared/plugin.ts` message keys.
 *
 * Kept apart from `petEventMessages.ts` on purpose: `index.ts` imports the
 * message table, so the table must not import `t` back from `index.ts`.
 */
export interface PetEventCopy {
  label: string
  trigger: string
  payloadHint: string
  frequencyHint: string
}

export const describePetEvent = (event: {
  labelKey: string
  triggerKey: string
  payloadHintKey: string
  frequencyHintKey: string
}): PetEventCopy => ({
  label: t(event.labelKey),
  trigger: t(event.triggerKey),
  payloadHint: t(event.payloadHintKey),
  frequencyHint: t(event.frequencyHintKey),
})
