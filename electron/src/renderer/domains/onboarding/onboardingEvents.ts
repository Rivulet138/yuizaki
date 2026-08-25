export const ONBOARDING_OPEN_EVENT = 'yuizaki:open-onboarding'

export const openOnboarding = (): void => {
  window.dispatchEvent(new CustomEvent(ONBOARDING_OPEN_EVENT))
}
