<template>
  <section class="connector-config-panel">
    <div class="connector-config-head">
      <div>
        <strong>{{ t('connectorPane.title', { name: connectorDisplayName(connectorId) }) }}</strong>
        <span>{{ connectorConfigs[connectorId]?.webhookPath || t('connectorPane.loadingConfig', { id: connectorId }) }}</span>
      </div>
      <div class="connector-config-head-actions">
        <el-button plain size="small" :disabled="!connectorConfigs[connectorId]?.webhookPath" @click="copyConnectorWebhookPath(connectorId)">{{ t('connectorPane.copyWebhook') }}</el-button>
        <el-switch
          v-model="connectorDrafts[connectorId].enabled"
          :disabled="savingConnectorIds.has(connectorId)"
          :aria-label="connectorDrafts[connectorId].enabled ? t('connectorPane.enabled') : t('connectorPane.disabled')"
        />
      </div>
    </div>
    <div class="connector-config-flags" v-if="connectorId !== 'qq' && connectorId !== 'wechat'">
      <el-tag size="small" :type="connectorConfigs[connectorId]?.botTokenConfigured ? 'success' : 'info'">{{ connectorId === 'discord' ? t('connectorPane.botTokenFallback') : t('connectorPane.botToken') }} {{ connectorConfigs[connectorId]?.botTokenConfigured ? t('connectorPane.configured') : t('connectorPane.notConfigured') }}</el-tag>
      <el-tag v-if="connectorId === 'telegram'" size="small" :type="connectorConfigs.telegram?.webhookSecretConfigured ? 'success' : 'info'">{{ t('connectorPane.webhookSecret') }} {{ connectorConfigs.telegram?.webhookSecretConfigured ? t('connectorPane.configured') : t('connectorPane.notConfigured') }}</el-tag>
      <el-tag v-if="connectorId === 'discord'" size="small" :type="connectorConfigs.discord?.publicKeyConfigured ? 'success' : 'info'">{{ t('connectorPane.publicKey') }} {{ connectorConfigs.discord?.publicKeyConfigured ? t('connectorPane.configured') : t('connectorPane.notConfigured') }}</el-tag>
    </div>
    <template v-if="connectorId === 'qq' || connectorId === 'wechat'">
      <div v-if="connectorId === 'qq'" class="connector-bridge-box connector-managed-bridge">
        <el-alert :title="t('connectorPane.bridge.managedIntro')" type="info" :closable="false" show-icon />
        <div class="connector-config-flags">
          <el-tag size="small" :type="qqBridgeTagType">{{ qqBridgeStateLabel }}</el-tag>
          <el-tag v-if="qqBridge?.installed" size="small" type="info">{{ t('connectorPane.bridge.version', { version: qqBridge?.version }) }}</el-tag>
          <el-tag v-if="qqBridge?.apiPort" size="small" type="info">{{ t('connectorPane.bridge.port', { port: qqBridge?.apiPort }) }}</el-tag>
          <el-tag v-if="qqBridge?.accountName || qqBridge?.accountId" size="small" type="success">
            {{ qqBridge?.accountName || t('connectorPane.bridge.accountOnly') }}<template v-if="qqBridge?.accountId">（{{ qqBridge?.accountId }}）</template>
          </el-tag>
        </div>
        <p v-if="qqBridge?.loginHint" class="connector-hint">{{ qqBridge?.loginHint }}</p>
        <pre v-if="qqBridge?.qrText" class="bridge-qr" :aria-label="t('connectorPane.bridge.qr')">{{ qqBridge?.qrText }}</pre>
        <div v-if="qqBridge?.installed" class="connector-secret-row">
          <el-input
            v-model="signServerDraft"
            :placeholder="t('connectorPane.bridge.signServerPlaceholder')"
            @keyup.enter="saveSignServer"
          />
          <el-button size="small" :loading="bridgeBusy" :disabled="bridgeBusy" @click="saveSignServer">{{ t('connectorPane.bridge.saveSignServer') }}</el-button>
        </div>
        <p v-if="qqBridge?.installed && !qqBridge?.signServerConfigured" class="connector-hint connector-hint-error">
          {{ t('connectorPane.bridge.signServerMissing') }}
        </p>
        <p v-if="qqBridge?.lastError" class="connector-hint connector-hint-error">{{ qqBridge?.lastError }}</p>
        <p v-else-if="!qqBridge?.installed" class="connector-hint">
          {{ t('connectorPane.bridge.riskNote') }}
        </p>
        <div class="connector-config-actions">
          <el-button
            v-if="!qqBridge?.installed"
            type="primary"
            size="small"
            :loading="bridgeBusy"
            @click="installManagedBridge"
          >{{ t('connectorPane.bridge.install') }}</el-button>
          <template v-else>
            <el-button v-if="!qqBridge?.running" type="primary" size="small" :loading="bridgeBusy" @click="startManagedBridge">{{ t('connectorPane.bridge.start') }}</el-button>
            <el-button v-else plain size="small" :loading="bridgeBusy" @click="refreshManagedBridge">{{ t('connectorPane.bridge.refresh') }}</el-button>
            <el-button v-if="qqBridge?.running" type="danger" plain size="small" :disabled="bridgeBusy" @click="stopManagedBridge">{{ t('connectorPane.bridge.stop') }}</el-button>
            <el-button type="danger" link size="small" :disabled="bridgeBusy" @click="logoutManagedBridge">{{ t('connectorPane.bridge.logout') }}</el-button>
          </template>
        </div>
      </div>
      <div class="connector-bridge-box">
        <el-alert :title="t('connectorPane.bridge.manualIntro')" type="warning" :closable="false" show-icon />
        <div v-if="!(connectorId === 'qq' && qqBridge?.installed)" class="connector-secret-row">
          <el-input v-model="connectorDrafts[connectorId].bridgeUrl" :placeholder="t('connectorPane.bridge.urlPlaceholder')" />
          <el-input v-model="connectorDrafts[connectorId].bridgeToken" type="password" show-password :placeholder="t('connectorPane.bridge.tokenPlaceholder')" />
        </div>
        <p v-if="connectorId === 'qq' && qqBridge?.installed" class="connector-hint">
          {{ t('connectorPane.bridge.managedHint', { url: qqBridge?.bridgeUrl || t('connectorPane.bridge.managedHintNoUrl') }) }}
        </p>
        <div class="connector-config-actions">
          <el-select v-model="connectorDrafts[connectorId].bridgeProtocol" size="small" :placeholder="t('connectorPane.bridge.protocolPlaceholder')">
            <el-option :label="t('connectorPane.bridge.protocolGeneric')" value="generic" />
            <el-option v-if="connectorId === 'qq'" label="OneBot 11" value="onebot11" />
            <el-option v-if="connectorId === 'qq'" label="OneBot 12" value="onebot12" />
          </el-select>
          <template v-if="connectorId === 'qq' && qqBridge?.installed">
            <span class="connector-hint">{{ t('connectorPane.bridge.managedLoginHint') }}</span>
          </template>
          <template v-else>
            <el-button type="primary" size="small" :loading="accountBusyIds.has(connectorId)" @click="loginPersonalAccount(connectorId)">{{ t('connectorPane.account.start') }}</el-button>
            <el-button plain size="small" :loading="accountBusyIds.has(connectorId)" @click="refreshPersonalAccount(connectorId)">{{ t('connectorPane.account.refresh') }}</el-button>
            <el-button type="danger" plain size="small" :disabled="accountBusyIds.has(connectorId)" @click="logoutPersonalAccount(connectorId)">{{ t('connectorPane.account.logout') }}</el-button>
            <el-button type="danger" link size="small" :disabled="accountBusyIds.has(connectorId)" @click="unbindPersonalAccount(connectorId)">{{ t('connectorPane.account.unbind') }}</el-button>
          </template>
        </div>
        <div v-if="connectorAccounts[connectorId]" class="connector-account-status">
          <span>{{ t('connectorPane.account.status', { state: accountStateLabel(connectorAccounts[connectorId].loginState) }) }}</span>
          <span v-if="connectorAccounts[connectorId].accountName">{{ t('connectorPane.account.name', { name: connectorAccounts[connectorId].accountName }) }}</span>
          <a v-if="connectorAccounts[connectorId].loginUrl" :href="connectorAccounts[connectorId].loginUrl || undefined" target="_blank" rel="noreferrer">{{ t('connectorPane.account.openLoginPage') }}</a>
        </div>
      </div>
    </template>
    <div v-if="connectorId !== 'qq' && connectorId !== 'wechat'" class="connector-secret-row">
      <el-input v-model="connectorDrafts[connectorId].botToken" type="password" show-password clearable :placeholder="connectorId === 'discord' ? t('connectorPane.discordTokenPlaceholder') : t('connectorPane.botTokenPlaceholder')" @input="connectorDrafts[connectorId].clearBotToken = false" />
      <el-button v-if="connectorConfigs[connectorId]?.botTokenConfigured || connectorDrafts[connectorId].clearBotToken" type="danger" link size="small" @click="clearConnectorSecret(connectorId, 'botToken')">{{ t('connectorPane.clear') }}</el-button>
    </div>
    <div v-if="connectorId === 'telegram'" class="connector-secret-row">
      <el-input v-model="connectorDrafts.telegram.webhookSecret" type="password" show-password clearable :placeholder="t('connectorPane.webhookSecretPlaceholder')" @input="connectorDrafts.telegram.clearWebhookSecret = false" />
      <el-button v-if="connectorConfigs.telegram?.webhookSecretConfigured || connectorDrafts.telegram.clearWebhookSecret" type="danger" link size="small" @click="clearConnectorSecret('telegram', 'webhookSecret')">{{ t('connectorPane.clear') }}</el-button>
    </div>
    <div v-if="connectorId === 'discord'" class="connector-secret-row">
      <el-input v-model="connectorDrafts.discord.publicKey" clearable :placeholder="t('connectorPane.publicKeyPlaceholder')" @input="connectorDrafts.discord.clearPublicKey = false" />
      <el-button v-if="connectorConfigs.discord?.publicKeyConfigured || connectorDrafts.discord.clearPublicKey" type="danger" link size="small" @click="clearConnectorSecret('discord', 'publicKey')">{{ t('connectorPane.clear') }}</el-button>
    </div>
    <div class="connector-config-actions">
      <el-button plain size="small" :loading="loadingConnectorConfigIds.has(connectorId)" @click="loadConnectorConfig(connectorId)">{{ t('connectorPane.reload') }}</el-button>
      <el-button plain size="small" :loading="probingConnectorIds.has(connectorId)" :disabled="connectorProbeRequest.loading || probingConnectorIds.has(connectorId)" @click="probeConnectorItem(connectorId)">{{ t('connectorPane.test') }}</el-button>
      <el-button type="primary" size="small" :loading="savingConnectorIds.has(connectorId)" @click="saveConnectorConfig(connectorId)">{{ t('connectorPane.save') }}</el-button>
      <el-button plain size="small" :loading="connectorDeliveriesRequest.loading" @click="loadConnectorDeliveries(connectorId)">{{ t('connectorPane.recentEvents') }}</el-button>
    </div>
    <div v-if="connectorProbeSnapshot(connectorId)" class="connector-probe-status">
      <el-tag size="small" :type="connectorProbeTagType(connectorProbeSnapshot(connectorId)!)">{{ connectorProbeStatusLabel(connectorProbeSnapshot(connectorId)!) }}</el-tag>
      <span v-if="connectorProbeSnapshot(connectorId)?.bridgeStatus">{{ t('connectorPane.bridgeStatusLabel', { status: connectorProbeSnapshot(connectorId)?.bridgeStatus }) }}</span>
      <details v-if="connectorProbeSnapshot(connectorId)?.statusCode || connectorProbeSnapshot(connectorId)?.errorCode" class="inline-diagnostic-details">
        <summary>{{ t('connectorPane.diagnostics') }}</summary>
        <span v-if="connectorProbeSnapshot(connectorId)?.statusCode">{{ t('connectorPane.serverResponded', { status: connectorProbeSnapshot(connectorId)?.statusCode }) }}</span>
        <span v-if="connectorProbeSnapshot(connectorId)?.errorCode" class="connector-probe-error">{{ t('connectorPane.errorCode', { code: connectorProbeSnapshot(connectorId)?.errorCode }) }}</span>
      </details>
    </div>
    <div v-if="connectorRecoverySnapshot(connectorId)" class="connector-recovery-telemetry">
      <span>{{ t('connectorPane.recoveryRuns', { count: connectorRecoverySnapshot(connectorId)?.runs ?? 0 }) }}</span>
      <span>{{ t('connectorPane.recoveryInspected', { count: connectorRecoverySnapshot(connectorId)?.inspected ?? 0 }) }}</span>
      <span>{{ t('connectorPane.recoveryRecovered', { count: connectorRecoverySnapshot(connectorId)?.recovered ?? 0 }) }}</span>
      <span>{{ t('connectorPane.recoveryFailed', { count: connectorRecoverySnapshot(connectorId)?.failed ?? 0 }) }}</span>
      <span>{{ t('connectorPane.recoveryLastRun', { time: formatRecoveryTime(connectorRecoverySnapshot(connectorId)?.lastRunAt) }) }}</span>
      <span v-if="connectorRecoverySnapshot(connectorId)?.lastError" class="connector-recovery-error">{{ connectorRecoverySnapshot(connectorId)?.lastError }}</span>
    </div>
    <div v-if="connectorDeliveryRows(connectorId).length" class="connector-delivery-list">
      <div v-for="delivery in connectorDeliveryRows(connectorId).slice(0, 5)" :key="delivery.deliveryKey" class="connector-delivery-item">
        <div>
          <strong>{{ connectorDeliveryStatusLabel(delivery.status) }}</strong>
          <span>{{ t('connectorPane.attemptCount', { count: delivery.attemptCount }) }}</span>
          <small v-if="delivery.lastError">{{ delivery.lastError }}</small>
          <details class="inline-diagnostic-details" v-if="delivery.eventId">
            <summary>{{ t('connectorPane.eventId') }}</summary>
            <code>{{ delivery.eventId }}</code>
          </details>
        </div>
        <el-button
          v-if="delivery.retryable"
          type="warning"
          link
          size="small"
          :loading="retryingDeliveryKeys.has(delivery.deliveryKey)"
          @click="retryDeliveryItem(connectorId, delivery.deliveryKey)"
        >
          {{ t('connectorPane.retry') }}
        </el-button>
        <el-button
          v-if="delivery.cancellable"
          type="danger"
          link
          size="small"
          :loading="cancellingEventIds.has(delivery.eventId)"
          @click="cancelConnectorEventItem(connectorId, delivery.eventId)"
        >
          {{ t('connectorPane.cancel') }}
        </el-button>
        <template v-if="delivery.resolvable">
          <el-button
            type="primary"
            link
            size="small"
            :loading="resolvingEventIds.has(delivery.eventId)"
            :disabled="resolvingEventIds.has(delivery.eventId)"
            @click="resolveConnectorEventItem(connectorId, delivery.eventId, 'delivered')"
          >
            {{ t('connectorPane.markDelivered') }}
          </el-button>
          <el-button
            type="warning"
            link
            size="small"
            :loading="resolvingEventIds.has(delivery.eventId)"
            :disabled="resolvingEventIds.has(delivery.eventId)"
            @click="resolveConnectorEventItem(connectorId, delivery.eventId, 'failed')"
          >
            {{ t('connectorPane.markFailed') }}
          </el-button>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/select/style/css'
import { ElSwitch } from 'element-plus'
import 'element-plus/es/components/switch/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { t } from '@/i18n'
import type { ConnectorPaneApi, MessageConnectorId } from './connector-pane'

const props = defineProps<{
  connectorId: MessageConnectorId
  api: ConnectorPaneApi
}>()

// The pane is presentational. Reading every binding off the typed `api` contract
// keeps this template independent of the panel's own template scope.
const connectorConfigs = computed(() => props.api.connectorConfigs)
const connectorDrafts = computed(() => props.api.connectorDrafts)
const connectorAccounts = computed(() => props.api.connectorAccounts)
const qqBridge = computed(() => props.api.qqBridge)
const qqBridgeStateLabel = computed(() => props.api.qqBridgeStateLabel)
const qqBridgeTagType = computed(() => props.api.qqBridgeTagType)
const bridgeBusy = computed(() => props.api.bridgeBusy)
const loadingConnectorConfigIds = computed(() => props.api.loadingConnectorConfigIds)
const savingConnectorIds = computed(() => props.api.savingConnectorIds)
const probingConnectorIds = computed(() => props.api.probingConnectorIds)
const accountBusyIds = computed(() => props.api.accountBusyIds)
const retryingDeliveryKeys = computed(() => props.api.retryingDeliveryKeys)
const cancellingEventIds = computed(() => props.api.cancellingEventIds)
const resolvingEventIds = computed(() => props.api.resolvingEventIds)
const connectorProbeRequest = computed(() => props.api.connectorProbeRequest)
const connectorDeliveriesRequest = computed(() => props.api.connectorDeliveriesRequest)
const signServerDraft = computed({
  get: () => props.api.signServerDraft,
  set: (value: string) => props.api.setSignServerDraft(value),
})

const connectorDisplayName = (connectorId: MessageConnectorId) => props.api.connectorDisplayName(connectorId)
const connectorProbeSnapshot = (connectorId: MessageConnectorId) => props.api.connectorProbeSnapshot(connectorId)
const connectorProbeStatusLabel = props.api.connectorProbeStatusLabel
const connectorProbeTagType = props.api.connectorProbeTagType
const connectorRecoverySnapshot = (connectorId: MessageConnectorId) => props.api.connectorRecoverySnapshot(connectorId)
const formatRecoveryTime = props.api.formatRecoveryTime
const connectorDeliveryRows = (connectorId: MessageConnectorId) => props.api.connectorDeliveryRows(connectorId)
const connectorDeliveryStatusLabel = props.api.connectorDeliveryStatusLabel
const accountStateLabel = props.api.accountStateLabel

const copyConnectorWebhookPath = (connectorId: MessageConnectorId) => props.api.copyConnectorWebhookPath(connectorId)
const loadConnectorConfig = (connectorId: MessageConnectorId) => props.api.loadConnectorConfig(connectorId)
const probeConnectorItem = (connectorId: MessageConnectorId) => props.api.probeConnectorItem(connectorId)
const saveConnectorConfig = (connectorId: MessageConnectorId) => props.api.saveConnectorConfig(connectorId)
const loadConnectorDeliveries = (connectorId: MessageConnectorId) => props.api.loadConnectorDeliveries(connectorId)
const clearConnectorSecret = props.api.clearConnectorSecret
const installManagedBridge = props.api.installManagedBridge
const startManagedBridge = props.api.startManagedBridge
const refreshManagedBridge = props.api.refreshManagedBridge
const stopManagedBridge = props.api.stopManagedBridge
const logoutManagedBridge = props.api.logoutManagedBridge
const saveSignServer = props.api.saveSignServer
const loginPersonalAccount = (connectorId: MessageConnectorId) => props.api.loginPersonalAccount(connectorId)
const refreshPersonalAccount = (connectorId: MessageConnectorId) => props.api.refreshPersonalAccount(connectorId)
const logoutPersonalAccount = (connectorId: MessageConnectorId) => props.api.logoutPersonalAccount(connectorId)
const unbindPersonalAccount = (connectorId: MessageConnectorId) => props.api.unbindPersonalAccount(connectorId)
const retryDeliveryItem = (connectorId: MessageConnectorId, deliveryKey: string) => props.api.retryDeliveryItem(connectorId, deliveryKey)
const cancelConnectorEventItem = (connectorId: MessageConnectorId, eventId: string) => props.api.cancelConnectorEventItem(connectorId, eventId)
const resolveConnectorEventItem = (connectorId: MessageConnectorId, eventId: string, outcome: 'delivered' | 'failed') =>
  props.api.resolveConnectorEventItem(connectorId, eventId, outcome)
</script>

<style scoped src="./ConnectorConfigPane.css"></style>
