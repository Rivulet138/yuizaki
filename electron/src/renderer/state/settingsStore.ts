import { reactive } from 'vue';
import { settingsClient } from '@/api/client';
import { isAuthMissingError } from '@/api/clients/http-client';
import type { SettingsResponse } from '@/api/clients/settings-client';
import {
  DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  DEFAULT_LLM_MAX_OUTPUT_TOKENS,
  DEFAULT_QDRANT_DOCKER_IMAGE,
  DEFAULT_VAD_MIN_SILENCE_MS,
} from '@/../shared/runtime-defaults';
import { logger } from '../logger';

const DEFAULT_EMBEDDING_MODEL = 'Qwen/Qwen3-Embedding-0.6B'

export interface SettingsState extends SettingsResponse {
  loading: boolean;
  error: string | null;
}

const state = reactive<SettingsState>({
  llm: {
    provider: 'custom',
    base_url: '',
    api_key: '',
    model: '',
    temperature: 1.2,
    top_p: 0.9,
    top_k: 500,
    min_p: 0,
    frequency_penalty: 0.2,
    presence_penalty: 0,
    repetition_penalty: 1,
    timeout: 60,
    context_max_tokens: DEFAULT_LLM_CONTEXT_MAX_TOKENS,
    default_max_output_tokens: DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    vision_enabled: false,
    vision_provider: 'custom',
    vision_base_url: '',
    vision_api_key: '',
    vision_model: '',
    vision_timeout: 30,
    vision_detail: 'low' as 'low' | 'high' | 'auto' | 'original',
    profiles: {},
  },
  tts: {
    genie_character: '',
    genie_model_dir: '',
    lang: 'ja',
    ref_audio: '',
    ref_text: '',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: 'genie-tts',
    base_url: '',
    api_key: '',
    model: 'tts-1',
    voice: 'alloy',
    timeout: 60,
  },
  asr: {
    provider: 'sherpa-onnx-online',
    base_url: '',
    api_key: '',
    timeout: 60,
    sensevoice_model: 'iic/SenseVoiceSmall',
    sensevoice_device: 'cpu',
    sherpa_model_path: '',
    sherpa_tokens_path: '',
    sherpa_num_threads: 2,
    sherpa_provider: 'cpu',
    language: 'zh',
    vad_threshold: 0.5,
    vad_min_silence_ms: DEFAULT_VAD_MIN_SILENCE_MS,
    asr_partial_every: 15,
  },
  svc: {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
  summary: {
    trigger_messages: 24,
    keep_recent_messages: 8,
    item_max_chars: 140,
    rewrite_interval_messages: 6,
    quality_scorer_mode: 'rule',
    quality_score_cooldown_seconds: 300,
    quality_score_budget_per_hour: 20,
  },
  system: {
    language: 'zh',
    theme: 'light',
  },
  memory: {
    backend: 'sqlite',
    sqlite_path: '',
    qdrant_url: '',
    qdrant_api_key: '',
    qdrant_collection: 'memories',
    qdrant_timeout: 10,
    qdrant_auto_start: true,
    qdrant_docker_image: DEFAULT_QDRANT_DOCKER_IMAGE,
    qdrant_docker_container: 'yuizaki-qdrant',
    qdrant_docker_volume: 'yuizaki-qdrant-storage',
    embedding_model: DEFAULT_EMBEDDING_MODEL,
    reranker_enabled: false,
    reranker_model: 'BAAI/bge-reranker-v2-m3',
    reranker_candidate_count: 32,
  },
  loading: false,
  error: null,
});

const errorMessage = (err: unknown, fallback: string): string => {
  if (err instanceof Error) return err.message || fallback
  if (typeof err === 'object' && err !== null) {
    const response = 'response' in err ? err.response : undefined
    if (typeof response === 'object' && response !== null && 'data' in response) {
      const data = response.data
      if (typeof data === 'object' && data !== null && 'detail' in data && typeof data.detail === 'string') {
        return data.detail
      }
    }
  }
  return fallback
}

function assignSection<K extends keyof SettingsState>(key: K, value: SettingsState[K]) {
  if (typeof state[key] === 'object' && state[key] !== null && typeof value === 'object' && value !== null) {
    Object.assign(state[key], value)
  } else {
    state[key] = value
  }
}

const normalizeTtsSettings = (value: Partial<SettingsResponse['tts']>): Partial<SettingsResponse['tts']> => ({
  ...value,
  provider: 'genie-tts',
})

const normalizeSettingsPayload = (updates: Partial<SettingsState>): Partial<SettingsState> => {
  if (!updates.tts || typeof updates.tts !== 'object') return updates
  return {
    ...updates,
    tts: normalizeTtsSettings(updates.tts) as SettingsState['tts'],
  }
}

export async function fetchSettings() {
  state.loading = true;
  state.error = null;
  try {
    const data = await settingsClient.load();
    if (data && typeof data === 'object') {
      const normalized = normalizeSettingsPayload(data as Partial<SettingsState>)
      for (const key of Object.keys(normalized) as Array<keyof SettingsState>) {
        if (key in state) {
          assignSection(key, normalized[key] as SettingsState[typeof key])
        }
      }
    }
  } catch (err: unknown) {
    state.error = errorMessage(err, 'Failed to fetch settings');
    if (isAuthMissingError(err)) {
      logger.warn('Fetch settings skipped until control authorization is available:', err);
    } else {
      logger.error('Fetch settings error:', err);
    }
  } finally {
    state.loading = false;
  }
}

export async function saveSettings(updates: Partial<SettingsState>) {
  state.loading = true;
  state.error = null;
  try {
    const normalized = normalizeSettingsPayload(updates)
    await settingsClient.save(normalized as Record<string, unknown>);
    for (const key of Object.keys(normalized) as Array<keyof SettingsState>) {
      if (key in state) {
        assignSection(key, normalized[key] as SettingsState[typeof key])
      }
    }
  } catch (err: unknown) {
    state.error = errorMessage(err, 'Failed to save settings');
    logger.error('Save settings error:', err);
    throw err;
  } finally {
    state.loading = false;
  }
}

export function useSettingsStore() {
  return {
    state,
    fetchSettings,
    saveSettings,
  };
}
