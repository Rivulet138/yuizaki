/**
 * Timing values shared by the focused realtime voice tests.
 * Keep the boundary explicit so unit and connection-level tests exercise the
 * same VAD contract instead of maintaining slightly different magic numbers.
 */
export const BARGE_IN_MIN_DURATION_MS = 160
export const SHORT_VAD_DURATION_MS = BARGE_IN_MIN_DURATION_MS - 1
export const SUSTAINED_VAD_DURATION_MS = BARGE_IN_MIN_DURATION_MS
export const FINALIZATION_GRACE_MS = 600
