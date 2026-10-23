import { definePanelMessages } from './definePanelMessages'

/**
 * Settings panel (`domains/settings/views/SettingsPanel.vue`).
 *
 * Only the strings the panel still rendered as Chinese literals live here. The
 * large `settings.*` inline table in `i18n/index.ts` is untouched.
 *
 * `settingsPanelTtsTokens` holds the persisted TTS option tokens: they are
 * backend enum values, not UI copy. The renderer stores and re-reads them
 * verbatim (python/modules/core/config.py and python/modules/tts/synthesizer.py
 * compare `split` against 禁用), so they must never be translated per locale.
 * They sit next to the panel messages so the panel view stays free of hardcoded
 * Chinese for the i18n inventory.
 */
export const settingsPanelTtsTokens = {
  qualityFirst: '质量优先',
  speedFirst: '速度优先',
  splitSmart: '智能切分',
  splitDisabled: '禁用',
  modeSerial: '串行推理',
  saveModeDisabled: '禁用自动保存',
}

export const settingsPanelMessages = definePanelMessages({
  'zh-CN': {
    'settingsPanel.ttsRuntimeDetails': '运行详情',
    'settingsPanel.resourceSherpaOnline': '流式语音识别',
    'settingsPanel.resourceSherpa': '离线语音识别',
    'settingsPanel.resourceEmbedding': '长期记忆嵌入',
    'settingsPanel.resourceSoulx': 'SoulX 变声',
    'settingsPanel.resourcePerModel': '按模型',
    'settingsPanel.message.inMemoryNoIndex': 'In-memory 后端没有持久化索引可重建',
    'settingsPanel.message.memoryBackendSwitching': '记忆后端仍在切换，请稍后重试',
    'settingsPanel.message.desktopShortcutSaveFailed': '桌面快捷键保存失败',
    'settingsPanel.message.shortcutNeedsModifier': '字母、数字和导航键至少需要一个修饰键',
    'settingsPanel.message.shortcutInvalid': '请输入有效的组合键，例如 Control+Shift+P',
    'settingsPanel.message.shortcutNeedsModifierOrFunctionKey': '桌面全局快捷键需要修饰键，或使用 F1-F24',
    'settingsPanel.message.shortcutDuplicate': '快捷键重复：{actions}',
    'settingsPanel.message.desktopInputReset': '桌面输入已恢复默认',
    'settingsPanel.message.desktopInputResetFailed': '恢复默认失败',
    'settingsPanel.message.resourceTaskBusy': '已有资源任务正在执行',
    'settingsPanel.message.downloadsCancelled': '已取消 {count} 个下载任务',
    'settingsPanel.message.noCancellableDownloads': '没有可取消的下载任务',
    'settingsPanel.message.finishCurrentResourceTask': '请先完成或取消当前资源任务',
    'settingsPanel.message.inUseSuffix': ' · 使用中：{list}',
    'settingsPanel.removeModelTitle': '永久卸载模型',
    'settingsPanel.removeModelConfirm': '永久卸载',
    'settingsPanel.message.removeModelOk': '已永久卸载 {label}，释放 {size}',
  },
  'en-US': {
    'settingsPanel.ttsRuntimeDetails': 'Runtime details',
    'settingsPanel.resourceSherpaOnline': 'Streaming speech recognition',
    'settingsPanel.resourceSherpa': 'Offline speech recognition',
    'settingsPanel.resourceEmbedding': 'Long-term memory embedding',
    'settingsPanel.resourceSoulx': 'SoulX voice changer',
    'settingsPanel.resourcePerModel': 'Per model',
    'settingsPanel.message.inMemoryNoIndex': 'The in-memory backend has no persistent index to rebuild',
    'settingsPanel.message.memoryBackendSwitching': 'The memory backend is still switching, please try again later',
    'settingsPanel.message.desktopShortcutSaveFailed': 'Failed to save the desktop shortcut',
    'settingsPanel.message.shortcutNeedsModifier': 'Letters, numbers and navigation keys need at least one modifier',
    'settingsPanel.message.shortcutInvalid': 'Enter a valid key combination, for example Control+Shift+P',
    'settingsPanel.message.shortcutNeedsModifierOrFunctionKey': 'Desktop global shortcuts need a modifier, or use F1-F24',
    'settingsPanel.message.shortcutDuplicate': 'Duplicate shortcut: {actions}',
    'settingsPanel.message.desktopInputReset': 'Desktop input restored to defaults',
    'settingsPanel.message.desktopInputResetFailed': 'Failed to restore defaults',
    'settingsPanel.message.resourceTaskBusy': 'Another resource task is already running',
    'settingsPanel.message.downloadsCancelled': 'Cancelled {count} download tasks',
    'settingsPanel.message.noCancellableDownloads': 'No download tasks to cancel',
    'settingsPanel.message.finishCurrentResourceTask': 'Finish or cancel the current resource task first',
    'settingsPanel.message.inUseSuffix': ' · In use: {list}',
    'settingsPanel.removeModelTitle': 'Permanently uninstall model',
    'settingsPanel.removeModelConfirm': 'Uninstall permanently',
    'settingsPanel.message.removeModelOk': 'Permanently uninstalled {label}, freed {size}',
  },
  'ja-JP': {
    'settingsPanel.ttsRuntimeDetails': '実行の詳細',
    'settingsPanel.resourceSherpaOnline': 'ストリーミング音声認識',
    'settingsPanel.resourceSherpa': 'オフライン音声認識',
    'settingsPanel.resourceEmbedding': '長期記憶の埋め込み',
    'settingsPanel.resourceSoulx': 'SoulX ボイスチェンジャー',
    'settingsPanel.resourcePerModel': 'モデル別',
    'settingsPanel.message.inMemoryNoIndex': 'In-memory バックエンドには再構築できる永続インデックスがありません',
    'settingsPanel.message.memoryBackendSwitching': 'メモリバックエンドを切り替え中です。しばらくしてから再試行してください',
    'settingsPanel.message.desktopShortcutSaveFailed': 'デスクトップショートカットの保存に失敗しました',
    'settingsPanel.message.shortcutNeedsModifier': '英字・数字・ナビゲーションキーには修飾キーが最低1つ必要です',
    'settingsPanel.message.shortcutInvalid': '有効なキーの組み合わせを入力してください（例：Control+Shift+P）',
    'settingsPanel.message.shortcutNeedsModifierOrFunctionKey': 'デスクトップのグローバルショートカットには修飾キーが必要です。または F1-F24 を使用してください',
    'settingsPanel.message.shortcutDuplicate': 'ショートカットが重複しています：{actions}',
    'settingsPanel.message.desktopInputReset': 'デスクトップ入力を既定値に戻しました',
    'settingsPanel.message.desktopInputResetFailed': '既定値への復元に失敗しました',
    'settingsPanel.message.resourceTaskBusy': '別のリソースタスクが実行中です',
    'settingsPanel.message.downloadsCancelled': '{count} 件のダウンロードタスクをキャンセルしました',
    'settingsPanel.message.noCancellableDownloads': 'キャンセルできるダウンロードタスクがありません',
    'settingsPanel.message.finishCurrentResourceTask': '先に現在のリソースタスクを完了またはキャンセルしてください',
    'settingsPanel.message.inUseSuffix': ' · 使用中：{list}',
    'settingsPanel.removeModelTitle': 'モデルを完全にアンインストール',
    'settingsPanel.removeModelConfirm': '完全にアンインストール',
    'settingsPanel.message.removeModelOk': '{label} を完全にアンインストールし、{size} を解放しました',
  },
})
