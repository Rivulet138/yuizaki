<template>
  <PanelShell :title="t('promptPanel.panel.title')" tone="companion">
    <div class="prompt-panel">
      <div v-if="contextSaveError" class="persona-save-error" role="alert">
        <span>{{ contextSaveError }}</span
        ><el-button
          size="small"
          plain
          @click="workspaceStore.retryContextSave(activeWorkspace.id)"
          >{{ copy("重试保存", "Retry save") }}</el-button
        >
      </div>
      <nav
        class="persona-tabs"
        role="tablist"
        :aria-label="copy('人格设定分区', 'Persona sections')"
      >
        <button
          v-for="view in views"
          :id="`persona-tab-${view.id}`"
          :key="view.id"
          type="button"
          role="tab"
          :aria-selected="activeView === view.id"
          :aria-controls="`persona-view-${view.id}`"
          :tabindex="activeView === view.id ? 0 : -1"
          :class="{ active: activeView === view.id }"
          @click="activeView = view.id"
          @keydown="onViewKeydown($event, view.id)"
        >
          {{ view.label }}
        </button>
      </nav>
      <div class="persona-workbench">
        <div
          class="persona-main"
          role="tabpanel"
          :id="`persona-view-${activeView}`"
          :aria-labelledby="`persona-tab-${activeView}`"
        >
          <WorkspacePromptEditor :section="activeView" />
          <details
            v-show="activeView === 'role'"
            class="prompt-card persona-source"
            id="companion-persona"
          >
            <summary>
              {{ copy("桌宠人格补充", "Companion persona")
              }}<span>{{ activeCompanion?.name || "—" }}</span>
            </summary>
            <header class="prompt-card-header">
              <div>
                <h3>
                  {{ copy("桌宠人格提示词", "Companion persona prompt") }}
                </h3>
                <span>{{
                  activeCompanion?.name || t("promptPanel.companion.noProfile")
                }}</span>
              </div>
              <div class="prompt-card-actions">
                <el-button
                  size="small"
                  plain
                  :loading="companionStore.loading"
                  @click="loadCompanions"
                  >{{ t("promptPanel.companion.refresh") }}</el-button
                >
                <el-button
                  size="small"
                  type="primary"
                  :disabled="
                    !activeCompanion ||
                    !companionPromptDirty ||
                    applyingCompanionRuntime
                  "
                  :loading="savingCompanionPrompt"
                  @click="saveCompanionPersonaPrompt"
                  >{{ t("promptPanel.companion.save") }}</el-button
                >
              </div>
            </header>
            <el-input
              v-model="companionPersonaPrompt"
              type="textarea"
              :rows="4"
              resize="vertical"
              :disabled="!activeCompanion"
              :aria-label="copy('桌宠人格提示词', 'Companion persona prompt')"
            />
            <el-button
              v-if="companionPromptDirty"
              size="small"
              plain
              @click="resetCompanionDraft"
              >{{
                copy(
                  "放弃草稿，读取当前已保存内容",
                  "Discard draft and use the current saved text",
                )
              }}</el-button
            >
            <p v-if="activeRuntimeApplication" role="status">
              {{
                activeRuntimeApplication.status === "applied"
                  ? copy(
                      "已保存的提示词已完成运行时应用。",
                      "Saved prompt applied to runtime.",
                    )
                  : copy(
                      "提示词已保存，运行时应用尚未完成。",
                      "Prompt saved; runtime application is incomplete.",
                    )
              }}
              <span v-if="activeRuntimeApplication.error">{{
                activeRuntimeApplication.error
              }}</span>
            </p>
            <el-button
              v-if="
                activeRuntimeApplication &&
                activeRuntimeApplication.status !== 'applied'
              "
              size="small"
              plain
              :loading="applyingCompanionRuntime"
              :disabled="savingCompanionPrompt"
              @click="applySavedCompanionPrompt"
              >{{
                copy(
                  "重试应用已保存的提示词",
                  "Retry applying the saved prompt",
                )
              }}</el-button
            >
            <details v-if="companionConflict" role="status">
              <summary>
                {{
                  copy(
                    "远端角色提示词已更新，已保留未保存草稿；查看远端内容",
                    "Remote persona changed; your draft is preserved. View remote text",
                  )
                }}
              </summary>
              <pre>{{ activeCompanion?.persona_prompt }}</pre>
            </details>
          </details>

          <SessionPersonaOverrides v-show="activeView === 'behavior'" />

          <section
            v-show="activeView === 'behavior'"
            class="prompt-card persona-source"
            id="workspace-instructions"
          >
            <header class="prompt-card-header">
              <div>
                <h3>{{ copy("工作区补充规则", "Workspace instructions") }}</h3>
                <span>{{ activeWorkspace.name }}</span>
              </div>
              <el-button
                size="small"
                type="primary"
                :disabled="!workspacePromptDirty"
                :loading="savingWorkspacePrompt"
                @click="saveWorkspaceSystemPrompt"
                >{{ t("promptPanel.workspace.save") }}</el-button
              >
            </header>
            <el-input
              v-model="workspaceSystemPrompt"
              type="textarea"
              :rows="4"
              resize="vertical"
              :aria-label="copy('工作区补充规则', 'Workspace instructions')"
            />
            <el-button
              v-if="workspacePromptDirty"
              size="small"
              plain
              @click="resetWorkspaceDraft"
              >{{
                copy(
                  "放弃草稿，读取当前已保存内容",
                  "Discard draft and use the current saved text",
                )
              }}</el-button
            >
            <details v-if="workspaceConflict" role="status">
              <summary>
                {{
                  copy(
                    "远端提示词已更新，已保留未保存草稿；查看远端内容",
                    "Remote prompt changed; your draft is preserved. View remote text",
                  )
                }}
              </summary>
              <pre>{{ activeWorkspace.system_prompt }}</pre>
            </details>
          </section>

        </div>
        <aside
          class="persona-inspector"
          :aria-label="copy('设定概览', 'Configuration overview')"
        >
          <header>
            <h3>{{ copy("设定概览", "Overview") }}</h3>
            <span>{{ modeLabel }}</span>
          </header>
          <dl>
            <div v-for="item in characterChecks" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd :class="{ 'is-empty': !item.ok }">{{ item.value }}</dd>
            </div>
            <div>
              <dt>{{ copy("世界书", "Lorebook") }}</dt>
              <dd>
                {{
                  activeWorkspace.context.worldBook.enabled
                    ? enabledWorldEntries
                    : copy("停用", "Disabled")
                }}
              </dd>
            </div>
          </dl>
          <div v-if="greetingReference" class="greeting-reference">
            <strong>{{ copy("开场白参考", "Greeting reference") }}</strong>
            <p>{{ greetingReference }}</p>
          </div>
        </aside>
      </div>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElButton } from "element-plus";
import "element-plus/es/components/button/style/css";
import { ElInput } from "element-plus";
import "element-plus/es/components/input/style/css";
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { ElMessage } from "element-plus";
import PanelShell from "@/shared/components/panel/PanelShell.vue";
import { currentLocale, t } from "@/i18n";
import { describeFailure } from "@/shared/errors/describe-error";
import WorkspacePromptEditor from "@/shared/components/prompt/WorkspacePromptEditor.vue";
import { useCompanionRuntimeBridge } from "@/app/composables/useCompanionRuntimeBridge";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useCompanionStore } from "@/stores/companionStore";
import SessionPersonaOverrides from "@/domains/prompt/components/SessionPersonaOverrides.vue";
import { getRoleCardGreeting } from "@/domains/prompt/character-card";

const workspaceStore = useWorkspaceStore();
const companionStore = useCompanionStore();
const { applyActiveCompanionRuntime } = useCompanionRuntimeBridge();

interface PromptDraft {
  text: string;
  base: string;
}
const workspaceDrafts = reactive<Record<string, PromptDraft>>({});
const companionDrafts = reactive<Record<string, PromptDraft>>({});
let promptPanelDisposed = false;
onBeforeUnmount(() => {
  promptPanelDisposed = true;
});
const workspaceSaves = reactive<Record<string, boolean>>({});
const companionSaves = reactive<Record<string, boolean>>({});
const runtimePending = reactive<Record<string, boolean>>({});
const savingWorkspacePrompt = computed(() => Boolean(workspaceSaves[activeWorkspace.value.id]));
const savingCompanionPrompt = computed(() => Boolean(companionSaves[activeCompanion.value?.id || ""]));
const applyingCompanionRuntime = computed(() => Boolean(runtimePending[runtimeKey(activeWorkspace.value.id, activeCompanion.value?.id || "")]));
const activeView = ref<"role" | "world" | "behavior">("role");
interface RuntimeApplication {
  prompt: string;
  status: "pending" | "applied" | "failed";
  error?: string;
}
const runtimeApplications = reactive<Record<string, RuntimeApplication>>({});
const runtimeKey = (workspaceId: string, companionId: string) =>
  JSON.stringify([workspaceId, companionId]);
const activeWorkspace = computed(() => workspaceStore.activeWorkspace);
const activeCompanion = computed(() => companionStore.activeCompanion);
const copy = (zh: string, en: string) =>
  currentLocale.value === "zh-CN" ? zh : en;
const syncDraft = (
  drafts: Record<string, PromptDraft>,
  id: string | undefined,
  serverText: string,
) => {
  if (!id) return;
  const draft = drafts[id];
  if (!draft) drafts[id] = { text: serverText, base: serverText };
  else if (draft.text === draft.base) draft.text = draft.base = serverText;
};
watch(
  () =>
    [activeWorkspace.value.id, activeWorkspace.value.system_prompt] as const,
  ([id, text]) => syncDraft(workspaceDrafts, id, text || ""),
  { immediate: true, flush: "sync" },
);
watch(
  () =>
    [activeCompanion.value?.id, activeCompanion.value?.persona_prompt] as const,
  ([id, text]) => syncDraft(companionDrafts, id, text || ""),
  { immediate: true, flush: "sync" },
);
const workspaceDraft = computed(
  () => workspaceDrafts[activeWorkspace.value.id],
);
const companionDraft = computed(() =>
  activeCompanion.value ? companionDrafts[activeCompanion.value.id] : undefined,
);
const workspaceSystemPrompt = computed({
  get: () => workspaceDraft.value?.text || "",
  set: (text: string) => {
    if (workspaceDraft.value) workspaceDraft.value.text = text;
  },
});
const companionPersonaPrompt = computed({
  get: () => companionDraft.value?.text || "",
  set: (text: string) => {
    if (companionDraft.value) companionDraft.value.text = text;
  },
});
const workspacePromptDirty = computed(
  () => workspaceDraft.value?.text !== workspaceDraft.value?.base,
);
const companionPromptDirty = computed(
  () => companionDraft.value?.text !== companionDraft.value?.base,
);
const workspaceConflict = computed(
  () =>
    workspacePromptDirty.value &&
    workspaceDraft.value?.base !== (activeWorkspace.value.system_prompt || ""),
);
const activeRuntimeApplication = computed(() => {
  const companion = activeCompanion.value;
  const application = companion
    ? runtimeApplications[runtimeKey(activeWorkspace.value.id, companion.id)]
    : undefined;
  return application?.prompt === (companion?.persona_prompt || "")
    ? application
    : undefined;
});
const resetWorkspaceDraft = () => {
  if (workspaceDraft.value)
    workspaceDraft.value.text = workspaceDraft.value.base =
      activeWorkspace.value.system_prompt || "";
};
const resetCompanionDraft = () => {
  if (companionDraft.value)
    companionDraft.value.text = companionDraft.value.base =
      activeCompanion.value?.persona_prompt || "";
};
const companionConflict = computed(
  () =>
    companionPromptDirty.value &&
    companionDraft.value?.base !==
      (activeCompanion.value?.persona_prompt || ""),
);

const loadCompanions = async () => {
  try {
    await companionStore.loadCompanions();
  } catch {
    ElMessage.warning(t("promptPanel.companion.loadFailed"));
  }
};
const commitSavedDraft = (
  draft: PromptDraft,
  submitted: string,
  saved: string,
) => {
  if (draft.text === submitted) draft.text = saved;
  draft.base = saved;
};
const saveWorkspaceSystemPrompt = async () => {
  if (savingWorkspacePrompt.value || !workspaceDraft.value) return;
  const id = activeWorkspace.value.id;
  const draft = workspaceDraft.value;
  const submitted = draft.text;
  workspaceSaves[id] = true;
  try {
    const saved = await workspaceStore.updateWorkspaceRemote(id, {
      system_prompt: submitted.trim() || null,
    });
    commitSavedDraft(draft, submitted, saved.system_prompt || "");
    ElMessage.success(t("promptPanel.workspace.saved"));
  } catch {
    ElMessage.error(t("promptPanel.workspace.saveFailed"));
  } finally {
    workspaceSaves[id] = false;
  }
};
const applySavedCompanionPrompt = async () => {
  const companion = activeCompanion.value;
  if (!companion || applyingCompanionRuntime.value || promptPanelDisposed)
    return;
  const workspaceId = activeWorkspace.value.id;
  const key = runtimeKey(workspaceId, companion.id);
  const application = runtimeApplications[key];
  if (!application || application.prompt !== (companion.persona_prompt || "")) {
    ElMessage.warning(
      copy(
        "已保存的提示词发生变化，请刷新后重新核对。",
        "The saved prompt changed. Refresh and check it again.",
      ),
    );
    return;
  }
  runtimePending[key] = true;
  try {
    await applyActiveCompanionRuntime();
    if (
      companion.id !== activeCompanion.value?.id ||
      workspaceId !== activeWorkspace.value.id ||
      application.prompt !== (activeCompanion.value.persona_prompt || "")
    ) {
      application.status = "pending";
      application.error = copy(
        "应用期间角色、工作区或已保存内容发生变化，请重新核对。",
        "Selection or saved content changed while applying. Check it again.",
      );
      return;
    }
    application.status = "applied";
    application.error = undefined;
    ElMessage.success(
      copy(
        "已保存的角色提示词已应用到当前运行时。",
        "Saved persona prompt applied to the current runtime.",
      ),
    );
  } catch (error) {
    application.status = "failed";
    application.error = describeFailure(
      error,
      copy("运行时应用失败，请重试。", "Runtime application failed. Retry."),
    );
    if (
      companion.id === activeCompanion.value?.id &&
      workspaceId === activeWorkspace.value.id
    )
      ElMessage.warning(
        copy("角色提示词已保存；", "Persona saved; ") + application.error,
      );
  } finally {
    runtimePending[key] = false;
  }
};

const saveCompanionPersonaPrompt = async () => {
  if (
    savingCompanionPrompt.value ||
    applyingCompanionRuntime.value ||
    !activeCompanion.value ||
    !companionDraft.value
  )
    return;
  const id = activeCompanion.value.id;
  const workspaceId = activeWorkspace.value.id;
  const draft = companionDraft.value;
  const submitted = draft.text;
  companionSaves[id] = true;
  try {
    const saved = await companionStore.updateCompanion(id, {
      persona_prompt: submitted.trim() || null,
    });
    commitSavedDraft(draft, submitted, saved.persona_prompt || "");
    runtimeApplications[runtimeKey(workspaceId, id)] = {
      prompt: saved.persona_prompt || "",
      status: "pending",
    };
  } catch {
    ElMessage.error(t("promptPanel.companion.saveFailed"));
    companionSaves[id] = false;
    return;
  }
  try {
    if (promptPanelDisposed) return;
    if (
      id === activeCompanion.value?.id &&
      workspaceId === activeWorkspace.value.id
    )
      await applySavedCompanionPrompt();
    else
      ElMessage.info(
        copy(
          "角色提示词已保存；当前角色已切换，尚未应用运行时。",
          "Persona saved; selection changed, runtime has not been applied.",
        ),
      );
  } finally {
    companionSaves[id] = false;
  }
};

const views = computed(
  () =>
    [
      { id: "role", label: copy("角色档案", "Character") },
      { id: "world", label: copy("世界书", "Lorebook") },
      { id: "behavior", label: copy("行为规则", "Behavior") },
    ] as const,
);
const onViewKeydown = (event: KeyboardEvent, id: string) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const index = views.value.findIndex((view) => view.id === id);
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? views.value.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + views.value.length) %
          views.value.length;
  activeView.value = views.value[next]!.id;
  (event.currentTarget as HTMLElement).parentElement
    ?.querySelector<HTMLButtonElement>(`#persona-tab-${activeView.value}`)
    ?.focus();
};
const roleCard = computed(() => activeWorkspace.value.context.roleCard);
const greetingReference = computed(() => getRoleCardGreeting(roleCard.value));
const modeLabel = computed(() =>
  t(`promptPanel.mode.${activeWorkspace.value.context.promptMode || "auto"}`),
);
const contextSaveError = computed(
  () => workspaceStore.contextSaveError?.[activeWorkspace.value.id] || "",
);
const enabledWorldEntries = computed(
  () =>
    activeWorkspace.value.context.worldBook.entries.filter(
      (entry) => entry.enabled,
    ).length,
);
const roleFields = computed(() => [
  { label: copy("角色名称", "Name"), value: roleCard.value.name, limit: 240 },
  {
    label: copy("身份与背景", "Identity and background"),
    value: roleCard.value.description || "",
    limit: 1600,
  },
  {
    label: copy("性格与价值观", "Personality and values"),
    value: roleCard.value.personality,
    limit: 1600,
  },
  {
    label: copy("关系与情境", "Relationship and scenario"),
    value: roleCard.value.scenario,
    limit: 1600,
  },
  {
    label: copy("表达与行为边界", "Voice and behavior"),
    value: roleCard.value.instructions,
    limit: 1600,
  },
  {
    label: copy("对话示例", "Example dialogue"),
    value: roleCard.value.exampleDialogue || "",
    limit: 1600,
  },
  {
    label: copy("开场白参考", "Greeting reference"),
    value: roleCard.value.firstMessage,
    limit: 500,
  },
]);
const characterChecks = computed(() => [
  {
    label: copy("角色卡", "Character card"),
    value: roleCard.value.enabled
      ? copy("启用", "Enabled")
      : copy("停用", "Disabled"),
    ok: roleCard.value.enabled,
  },
  ...roleFields.value
    .slice(0, 6)
    .map((field) => ({
      label: field.label,
      value: field.value.trim()
        ? `${field.value.length}`
        : copy("未填写", "Empty"),
      ok: Boolean(field.value.trim()),
    })),
]);
onMounted(() => {
  if (!companionStore.companions.length) {
    void loadCompanions();
  }
});
</script>

<style scoped>
.prompt-panel {
  --el-text-color-primary: var(--yui-text);
  --el-text-color-regular: var(--yui-text);
  --el-text-color-secondary: var(--yui-muted);
  --el-text-color-placeholder: var(--yui-muted);
  --el-bg-color: var(--yui-surface-raised);
  --el-fill-color-blank: var(--yui-surface-raised);
  --el-fill-color-light: var(--yui-surface-muted);
  --el-border-color: var(--yui-border);
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}
.prompt-panel :deep(.el-input__count),
.prompt-panel :deep(.el-textarea .el-input__count) {
  color: var(--yui-muted);
  background: var(--yui-surface-raised);
}
.persona-tabs {
  display: flex;
  gap: 6px;
  border-bottom: 1px solid var(--yui-border);
  padding-bottom: 8px;
}
.persona-tabs button {
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  color: var(--yui-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  padding: 9px 16px;
  cursor: pointer;
  white-space: nowrap;
}
.persona-tabs button:hover {
  background: var(--yui-surface-muted);
  color: var(--yui-text);
}
.persona-tabs button.active {
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
  border-color: var(--yui-border);
}
.persona-tabs button:focus-visible,
.persona-source summary:focus-visible {
  outline: 2px solid var(--yui-accent);
  outline-offset: 3px;
}
.persona-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 250px;
  gap: 22px;
  align-items: start;
}
.persona-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.persona-inspector {
  position: sticky;
  top: 0;
  padding: 18px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  min-width: 0;
}
.persona-inspector header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.persona-inspector h3 {
  margin: 0;
  font-size: 14px;
  color: var(--yui-text);
}
.persona-inspector header > span {
  font-size: 12px;
  color: var(--yui-accent);
}
.persona-inspector dl {
  margin: 18px 0;
  display: grid;
  gap: 13px;
  font-size: 12px;
}
.persona-inspector dl > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.persona-inspector dt {
  color: var(--yui-muted);
}
.persona-inspector dd {
  margin: 0;
  color: var(--yui-text);
  font-variant-numeric: tabular-nums;
}
.persona-inspector dd.is-empty {
  color: var(--yui-muted);
}
.greeting-reference {
  border-top: 1px solid var(--yui-border);
  padding-top: 16px;
  margin-bottom: 16px;
  font-size: 12px;
}
.greeting-reference p {
  line-height: 1.7;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.prompt-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 16px;
}
.persona-source summary {
  cursor: pointer;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 650;
}
.persona-source summary span {
  float: right;
  font-size: 12px;
  color: var(--yui-muted);
  font-weight: 400;
}
.persona-source[open] > summary {
  margin-bottom: 16px;
}
.prompt-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.prompt-card-header h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 13px;
}
.prompt-card-header span {
  display: block;
  margin-top: 5px;
  color: var(--yui-muted);
  font-size: 12px;
}
.prompt-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.persona-save-error {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--el-color-danger);
  font-size: 13px;
}
@media (max-width: 1180px) {
  .persona-workbench {
    grid-template-columns: minmax(0, 1fr);
  }
  .persona-inspector {
    position: static;
  }
  .persona-inspector dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 24px;
  }
}
@media (max-width: 760px) {
  .persona-tabs {
    gap: 2px;
  }
  .persona-tabs button {
    padding: 9px 10px;
  }
  .persona-inspector dl {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    transition: none !important;
  }
}
</style>
