import { beforeEach, describe, expect, it, vi } from 'vitest'

const { requestJsonMock } = vi.hoisted(() => ({
  requestJsonMock: vi.fn(),
}))

vi.mock('./http-client', () => ({
  CONTROL_ORIGIN: 'http://127.0.0.1:8001',
  requestBlob: vi.fn(),
  requestJson: requestJsonMock,
}))

import { systemClient } from './system-client'

describe('systemClient connector delivery normalization', () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  it('fails closed for malformed counters and timestamps', async () => {
    requestJsonMock.mockResolvedValue({
      ok: true,
      connector_id: 'telegram',
      items: [{
        delivery_key: 'delivery-1',
        idempotency_key: 'idempotency-1',
        connector_id: 'telegram',
        event_id: 'event-1',
        status: 'failed',
        attempt_count: 'not-a-number',
        updated_at: Number.POSITIVE_INFINITY,
        delivered_at: -1,
        last_error: 'x'.repeat(500),
        resolvable: true,
      }],
    })

    const snapshot = await systemClient.connectorDeliveries('telegram')
    const [delivery] = snapshot.items

    expect(delivery).toMatchObject({
      attemptCount: 0,
      updatedAt: 0,
      deliveredAt: null,
      retryable: true,
      cancellable: false,
      resolvable: true,
    })
    expect(delivery.lastError).toHaveLength(160)
  })

  it('does not make unknown effects retryable or cancellable', async () => {
    requestJsonMock.mockResolvedValue({
      ok: true,
      connector_id: 'discord',
      items: [{
        delivery_key: 'delivery-2',
        idempotency_key: 'idempotency-2',
        connector_id: 'discord',
        event_id: 'event-2',
        status: 'unknown_effect',
        attempt_count: 2,
        updated_at: 42,
        delivered_at: null,
        last_error: null,
        resolvable: true,
      }],
    })

    const [delivery] = (await systemClient.connectorDeliveries('discord')).items

    expect(delivery.status).toBe('unknown_effect')
    expect(delivery.retryable).toBe(false)
    expect(delivery.cancellable).toBe(false)
    expect(delivery.resolvable).toBe(true)
  })

  it('preserves a bounded, human-resolvable unknown effect without enabling retry', async () => {
    requestJsonMock.mockResolvedValue({
      ok: true,
      connector_id: 'telegram',
      items: [{
        delivery_key: 'delivery-3',
        idempotency_key: 'idempotency-3',
        connector_id: 'telegram',
        event_id: 'event-3',
        status: 'unknown_effect',
        attempt_count: 3,
        updated_at: 99,
        delivered_at: null,
        last_error: 'provider response was lost',
        resolvable: true,
      }],
    })

    const [delivery] = (await systemClient.connectorDeliveries('telegram')).items

    expect(delivery).toMatchObject({
      status: 'unknown_effect',
      attemptCount: 3,
      retryable: false,
      cancellable: false,
      resolvable: true,
    })
  })
})
