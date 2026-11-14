import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import { petControl } from '@/utils/petControl'
import { DEFAULT_PET_CONTROL_STATE, type PetModelCatalogPayload } from '../../../../shared/pet-control'
import { useSystemOverview } from './useSystemOverview'

vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/stores/systemStore', () => ({ useSystemStore: () => ({}) }))
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('@/utils/petControl', () => ({ petControl: { getState: vi.fn(), getCatalog: vi.fn(), setScale: vi.fn(), setOpacity: vi.fn(), setModel: vi.fn(), setVisible: vi.fn(), reloadRenderer: vi.fn(), setInteractMode: vi.fn(), setClickThrough: vi.fn(), setLocked: vi.fn(), setDoNotDisturb: vi.fn(), snapBottomRight: vi.fn() } }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => vi.resetAllMocks())

describe('overview pet snapshot ordering', () => {
  it('does not restore an older scale from a poll that predates a successful edit', async () => {
    const older = deferred<typeof DEFAULT_PET_CONTROL_STATE>()
    vi.mocked(petControl.getState).mockReturnValue(older.promise)
    vi.mocked(petControl.setScale).mockResolvedValue({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.5 })
    const domain = useSystemOverview()
    const polling = domain.syncPetData(true, false)
    await domain.applyScale(1.5)
    older.resolve({ ...DEFAULT_PET_CONTROL_STATE, scale: 1 })
    await polling
    expect(domain.petState.value.scale).toBe(1.5)
  })

  it('keeps the latest refresh when state replies arrive out of order', async () => {
    const older = deferred<typeof DEFAULT_PET_CONTROL_STATE>()
    vi.mocked(petControl.getState).mockReturnValueOnce(older.promise).mockResolvedValueOnce({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.2 })
    const domain = useSystemOverview()
    const polling = domain.syncPetData(true, false)
    await domain.syncPetData(true, false)
    older.resolve({ ...DEFAULT_PET_CONTROL_STATE, scale: 1 })
    await polling
    expect(domain.scaleDraft.value).toBe(1.2)
  })
})


const catalogFor = (id: string): PetModelCatalogPayload => ({
  activeModelId: id,
  models: [{ id, name: id, type: 'live2d', assetPath: `${id}.model3.json`, motions: [], expressions: [], emotions: [] }],
})

describe('overview catalog snapshot ordering', () => {
  it.each([false, true])('accepts the initial catalog after a scale edit (with state-only poll: %s)', async (pollAfterEdit) => {
    const catalog = deferred<PetModelCatalogPayload>()
    vi.mocked(petControl.getCatalog).mockReturnValueOnce(catalog.promise)
    vi.mocked(petControl.getState).mockResolvedValueOnce({ ...DEFAULT_PET_CONTROL_STATE, scale: 1, modelId: null })
      .mockResolvedValueOnce({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.5, modelId: null })
    vi.mocked(petControl.setScale).mockResolvedValue({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.5, modelId: null })
    const domain = useSystemOverview()
    const initial = domain.syncPetData(true)
    await domain.applyScale(1.5)
    if (pollAfterEdit) await domain.syncPetData(true, false)
    catalog.resolve(catalogFor('initial-model'))
    await initial
    expect(domain.petCatalog.value).toEqual(catalogFor('initial-model'))
    expect(domain.selectedModelId.value).toBe('initial-model')
    expect(domain.petState.value.scale).toBe(1.5)
    if (pollAfterEdit) expect(domain.scaleDraft.value).toBe(1.5)
    expect(petControl.getCatalog).toHaveBeenCalledOnce()
  })

  it('rejects an older catalog after a newer catalog refresh, retaining the latest pet state and selection', async () => {
    const olderCatalog = deferred<PetModelCatalogPayload>()
    vi.mocked(petControl.getCatalog).mockReturnValueOnce(olderCatalog.promise).mockResolvedValueOnce(catalogFor('new-model'))
    vi.mocked(petControl.getState).mockResolvedValueOnce({ ...DEFAULT_PET_CONTROL_STATE, scale: 1, modelId: 'old-model' })
      .mockResolvedValueOnce({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.2, modelId: 'new-model' })
    const domain = useSystemOverview()
    const initial = domain.syncPetData(true)
    await domain.syncPetData(true)
    olderCatalog.resolve(catalogFor('old-model'))
    await initial
    expect(domain.petCatalog.value).toEqual(catalogFor('new-model'))
    expect(domain.selectedModelId.value).toBe('new-model')
    expect(domain.petState.value.scale).toBe(1.2)
    expect(domain.scaleDraft.value).toBe(1.2)
  })
})


describe('overview mutation snapshot ordering', () => {
  const writes = [
    ['applyScale', 'setScale', 0.9, 1.4],
    ['applyOpacity', 'setOpacity', 0.4, 0.8],
    ['setInteractMode', 'setInteractMode', false, true],
    ['setClickThrough', 'setClickThrough', false, true],
    ['setLocked', 'setLocked', false, true],
    ['setDoNotDisturb', 'setDoNotDisturb', false, true],
    ['dockBottomRight', 'snapBottomRight', undefined, undefined],
  ] as const

  it.each(writes)('rejects the older full state from %s after a newer write', async (action, client, first, second) => {
    const older = deferred<typeof DEFAULT_PET_CONTROL_STATE>()
    const newer = { ...DEFAULT_PET_CONTROL_STATE, scale: 1.4, opacity: 0.8 }
    vi.mocked(petControl[client]).mockReturnValueOnce(older.promise).mockResolvedValueOnce(newer)
    const domain = useSystemOverview()
    const oldWrite = domain[action](first as never)
    await domain[action](second as never)
    older.resolve({ ...DEFAULT_PET_CONTROL_STATE, scale: 0.9, opacity: 0.4 })
    await oldWrite
    expect(domain.petState.value).toEqual(newer)
    if (action === 'applyOpacity') expect(domain.opacityDraft.value).toBe(0.8)
  })

  it('orders full-state commits across different controls', async () => {
    const older = deferred<typeof DEFAULT_PET_CONTROL_STATE>()
    vi.mocked(petControl.setScale).mockReturnValueOnce(older.promise)
    const newer = { ...DEFAULT_PET_CONTROL_STATE, scale: 1.4, opacity: 0.8 }
    vi.mocked(petControl.setOpacity).mockResolvedValueOnce(newer)
    const domain = useSystemOverview()
    const oldWrite = domain.applyScale(1.4)
    await domain.applyOpacity(0.8)
    older.resolve({ ...DEFAULT_PET_CONTROL_STATE, scale: 1.4, opacity: 0.4 })
    await oldWrite
    expect(domain.petState.value).toEqual(newer)
    expect(domain.opacityDraft.value).toBe(0.8)
  })

  it('preserves a superseded model operation ACK without committing its state or starting a stale readback', async () => {
    const older = deferred<typeof DEFAULT_PET_CONTROL_STATE>()
    vi.mocked(petControl.setModel).mockReturnValueOnce(older.promise)
    const newer = { ...DEFAULT_PET_CONTROL_STATE, scale: 1.4, modelId: 'new-model' }
    vi.mocked(petControl.setScale).mockResolvedValueOnce(newer)
    const domain = useSystemOverview()
    domain.selectedModelId.value = 'old-model'
    const switching = domain.applyModel()
    await domain.applyScale(1.4)
    older.resolve({ ...DEFAULT_PET_CONTROL_STATE, modelId: 'old-model' })
    await switching
    expect(domain.petState.value).toEqual(newer)
    expect(petControl.getState).not.toHaveBeenCalled()
    expect(petControl.reloadRenderer).toHaveBeenCalledOnce()
    expect(ElMessage.success).toHaveBeenCalledWith('overview.modelSwitched')
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('does not let an old visibility ACK start a readback over a newer edit', async () => {
    const older = deferred<void>()
    vi.mocked(petControl.setVisible).mockReturnValueOnce(older.promise)
    const newer = { ...DEFAULT_PET_CONTROL_STATE, visible: false, scale: 1.4 }
    vi.mocked(petControl.setScale).mockResolvedValueOnce(newer)
    const domain = useSystemOverview()
    const showing = domain.setPetVisible(true)
    await domain.applyScale(1.4)
    older.resolve()
    await showing
    expect(domain.petState.value).toEqual(newer)
    expect(petControl.getState).not.toHaveBeenCalled()
  })

  it('keeps the latest successful model readback and ACK', async () => {
    const state = { ...DEFAULT_PET_CONTROL_STATE, modelId: 'new-model' }
    vi.mocked(petControl.setModel).mockResolvedValueOnce(state)
    vi.mocked(petControl.getState).mockResolvedValueOnce(state)
    vi.mocked(petControl.getCatalog).mockResolvedValueOnce(catalogFor('new-model'))
    const domain = useSystemOverview()
    domain.selectedModelId.value = 'new-model'
    await domain.applyModel()
    expect(domain.petState.value).toEqual(state)
    expect(domain.petCatalog.value).toEqual(catalogFor('new-model'))
    expect(ElMessage.success).toHaveBeenCalledWith('overview.modelSwitched')
  })
})
