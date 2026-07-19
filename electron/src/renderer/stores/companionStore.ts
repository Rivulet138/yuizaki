import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { companionClient, type CompanionRecord } from '@/api/clients/companion-client'

export const useCompanionStore = defineStore('companion', () => {
  const companions = ref<CompanionRecord[]>([])
  const activeCompanionId = ref<string>('default')
  const loading = ref(false)

  const activeCompanion = computed(() =>
    companions.value.find((c) => c.id === activeCompanionId.value) ?? companions.value[0] ?? null,
  )

  const loadCompanions = async () => {
    loading.value = true
    try {
      const payload = await companionClient.list()
      companions.value = Array.isArray(payload.companions) ? payload.companions : []
      if (!companions.value.some((c) => c.id === activeCompanionId.value)) {
        activeCompanionId.value = companions.value[0]?.id || 'default'
      }
    } finally {
      loading.value = false
    }
  }

  const setActiveCompanion = (companionId: string) => {
    activeCompanionId.value = companionId
  }

  const createCompanion = async (payload: { name: string; model_type?: string; model_id?: string; persona_prompt?: string }) => {
    const companion = await companionClient.create(payload)
    companions.value.unshift(companion)
    activeCompanionId.value = companion.id
    return companion
  }

  const updateCompanion = async (companionId: string, patch: Partial<Omit<CompanionRecord, 'id' | 'created_at' | 'updated_at'>>) => {
    const updated = await companionClient.update(companionId, patch)
    companions.value = companions.value.map((c) => (c.id === companionId ? updated : c))
    return updated
  }

  const deleteCompanion = async (companionId: string) => {
    await companionClient.remove(companionId)
    companions.value = companions.value.filter((c) => c.id !== companionId)
    if (activeCompanionId.value === companionId) {
      activeCompanionId.value = companions.value[0]?.id || 'default'
    }
  }

  return {
    companions,
    activeCompanionId,
    activeCompanion,
    loading,
    loadCompanions,
    setActiveCompanion,
    createCompanion,
    updateCompanion,
    deleteCompanion,
  }
})
