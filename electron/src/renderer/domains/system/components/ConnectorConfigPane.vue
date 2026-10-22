<template>
  <section class="connector-config-panel">
    <div class="connector-config-head">
      <div>
        <strong>{{ connectorDisplayName(connectorId) }} 设置</strong>
        <span>{{ connectorConfigs[connectorId]?.webhookPath || `加载 ${connectorId} 配置` }}</span>
      </div>
      <div class="connector-config-head-actions">
        <el-button plain size="small" :disabled="!connectorConfigs[connectorId]?.webhookPath" @click="copyConnectorWebhookPath(connectorId)">复制回调路径</el-button>
        <el-switch v-model="connectorDrafts[connectorId].enabled" :disabled="savingConnectorIds.has(connectorId)" />
      </div>
    </div>
    <div class="connector-config-flags" v-if="connectorId !== 'qq' && connectorId !== 'wechat'">
      <el-tag size="small" :type="connectorConfigs[connectorId]?.botTokenConfigured ? 'success' : 'info'">{{ connectorId === 'discord' ? '降级 Bot Token' : 'Bot Token' }} {{ connectorConfigs[connectorId]?.botTokenConfigured ? '已配置' : '未配置' }}</el-tag>
      <el-tag v-if="connectorId === 'telegram'" size="small" :type="connectorConfigs.telegram?.webhookSecretConfigured ? 'success' : 'info'">Webhook Secret {{ connectorConfigs.telegram?.webhookSecretConfigured ? '已配置' : '未配置' }}</el-tag>
      <el-tag v-if="connectorId === 'discord'" size="small" :type="connectorConfigs.discord?.publicKeyConfigured ? 'success' : 'info'">Public Key {{ connectorConfigs.discord?.publicKeyConfigured ? '已配置' : '未配置' }}</el-tag>
    </div>
    <template v-if="connectorId === 'qq' || connectorId === 'wechat'">
      <div v-if="connectorId === 'qq'" class="connector-bridge-box connector-managed-bridge">
        <el-alert title="内置桥：由 Yuizaki 自行下载并托管桥进程，无需另装 OneBot 服务。" type="info" :closable="false" show-icon />
        <div class="connector-config-flags">
          <el-tag size="small" :type="qqBridgeTagType">{{ qqBridgeStateLabel }}</el-tag>
          <el-tag v-if="qqBridge?.installed" size="small" type="info">版本 {{ qqBridge?.version }}</el-tag>
          <el-tag v-if="qqBridge?.apiPort" size="small" type="info">端口 {{ qqBridge?.apiPort }}</el-tag>
          <el-tag v-if="qqBridge?.accountName || qqBridge?.accountId" size="small" type="success">
            {{ qqBridge?.accountName || '账号' }}<template v-if="qqBridge?.accountId">（{{ qqBridge?.accountId }}）</template>
          </el-tag>
        </div>
        <p v-if="qqBridge?.loginHint" class="connector-hint">{{ qqBridge?.loginHint }}</p>
        <pre v-if="qqBridge?.qrText" class="bridge-qr" aria-label="QQ 登录二维码">{{ qqBridge?.qrText }}</pre>
        <div v-if="qqBridge?.installed" class="connector-secret-row">
          <el-input
            v-model="signServerDraft"
            placeholder="签名服务地址（该协议版本登录必需），例如 https://…/api/sign"
            @keyup.enter="saveSignServer"
          />
          <el-button size="small" :loading="bridgeBusy" :disabled="bridgeBusy" @click="saveSignServer">保存签名服务</el-button>
        </div>
        <p v-if="qqBridge?.installed && !qqBridge?.signServerConfigured" class="connector-hint connector-hint-error">
          未配置签名服务时，桥会在登录阶段直接失败（日志出现 Signer server returned …），不会出现二维码。
        </p>
        <p v-if="qqBridge?.lastError" class="connector-hint connector-hint-error">{{ qqBridge?.lastError }}</p>
        <p v-else-if="!qqBridge?.installed" class="connector-hint">
          首次使用会下载第三方个人账号客户端（约 34 MB），存在账号封禁风险；上游仓库未声明开源许可，本项目不分发该二进制。
        </p>
        <div class="connector-config-actions">
          <el-button
            v-if="!qqBridge?.installed"
            type="primary"
            size="small"
            :loading="bridgeBusy"
            @click="installManagedBridge"
          >下载并安装内置桥</el-button>
          <template v-else>
            <el-button v-if="!qqBridge?.running" type="primary" size="small" :loading="bridgeBusy" @click="startManagedBridge">启动并扫码</el-button>
            <el-button v-else plain size="small" :loading="bridgeBusy" @click="refreshManagedBridge">刷新状态</el-button>
            <el-button v-if="qqBridge?.running" type="danger" plain size="small" :disabled="bridgeBusy" @click="stopManagedBridge">停止桥</el-button>
            <el-button type="danger" link size="small" :disabled="bridgeBusy" @click="logoutManagedBridge">退出并清除登录</el-button>
          </template>
        </div>
      </div>
      <div class="connector-bridge-box">
        <el-alert title="个人账号桥接，稳定性取决于桥接程序。" type="warning" :closable="false" show-icon />
        <div v-if="!(connectorId === 'qq' && qqBridge?.installed)" class="connector-secret-row">
          <el-input v-model="connectorDrafts[connectorId].bridgeUrl" placeholder="兼容桥地址，例如 http://127.0.0.1:3000" />
          <el-input v-model="connectorDrafts[connectorId].bridgeToken" type="password" show-password placeholder="桥接令牌（启用必填）" />
        </div>
        <p v-if="connectorId === 'qq' && qqBridge?.installed" class="connector-hint">
          桥地址与令牌由内置桥自动写入（{{ qqBridge?.bridgeUrl || '启动后生成' }}），无需手工填写。
        </p>
        <div class="connector-config-actions">
          <el-select v-model="connectorDrafts[connectorId].bridgeProtocol" size="small" placeholder="桥协议">
            <el-option label="通用桥 API" value="generic" />
            <el-option v-if="connectorId === 'qq'" label="OneBot 11" value="onebot11" />
            <el-option v-if="connectorId === 'qq'" label="OneBot 12" value="onebot12" />
          </el-select>
          <template v-if="connectorId === 'qq' && qqBridge?.installed">
            <span class="connector-hint">账号登录由上方「内置桥」统一管理。</span>
          </template>
          <template v-else>
            <el-button type="primary" size="small" :loading="accountBusyIds.has(connectorId)" @click="loginPersonalAccount(connectorId)">开始登录</el-button>
            <el-button plain size="small" :loading="accountBusyIds.has(connectorId)" @click="refreshPersonalAccount(connectorId)">刷新状态</el-button>
            <el-button type="danger" plain size="small" :disabled="accountBusyIds.has(connectorId)" @click="logoutPersonalAccount(connectorId)">退出账号</el-button>
            <el-button type="danger" link size="small" :disabled="accountBusyIds.has(connectorId)" @click="unbindPersonalAccount(connectorId)">清除桥接配置</el-button>
          </template>
        </div>
        <div v-if="connectorAccounts[connectorId]" class="connector-account-status">
          <span>状态：{{ accountStateLabel(connectorAccounts[connectorId].loginState) }}</span>
          <span v-if="connectorAccounts[connectorId].accountName">账号：{{ connectorAccounts[connectorId].accountName }}</span>
          <a v-if="connectorAccounts[connectorId].loginUrl" :href="connectorAccounts[connectorId].loginUrl || undefined" target="_blank" rel="noreferrer">打开登录页</a>
        </div>
      </div>
    </template>
    <div v-if="connectorId !== 'qq' && connectorId !== 'wechat'" class="connector-secret-row">
      <el-input v-model="connectorDrafts[connectorId].botToken" type="password" show-password clearable :placeholder="connectorId === 'discord' ? '可选 Bot Token；Interaction 过期后用于频道降级' : 'Bot Token；留空表示不修改'" @input="connectorDrafts[connectorId].clearBotToken = false" />
      <el-button v-if="connectorConfigs[connectorId]?.botTokenConfigured || connectorDrafts[connectorId].clearBotToken" type="danger" link size="small" @click="clearConnectorSecret(connectorId, 'botToken')">清除</el-button>
    </div>
    <div v-if="connectorId === 'telegram'" class="connector-secret-row">
      <el-input v-model="connectorDrafts.telegram.webhookSecret" type="password" show-password clearable placeholder="Webhook Secret（启用必填）；留空不修改" @input="connectorDrafts.telegram.clearWebhookSecret = false" />
      <el-button v-if="connectorConfigs.telegram?.webhookSecretConfigured || connectorDrafts.telegram.clearWebhookSecret" type="danger" link size="small" @click="clearConnectorSecret('telegram', 'webhookSecret')">清除</el-button>
    </div>
    <div v-if="connectorId === 'discord'" class="connector-secret-row">
      <el-input v-model="connectorDrafts.discord.publicKey" clearable placeholder="Discord Public Key（64 位十六进制）；留空表示不修改" @input="connectorDrafts.discord.clearPublicKey = false" />
      <el-button v-if="connectorConfigs.discord?.publicKeyConfigured || connectorDrafts.discord.clearPublicKey" type="danger" link size="small" @click="clearConnectorSecret('discord', 'publicKey')">清除</el-button>
    </div>
    <div class="connector-config-actions">
      <el-button plain size="small" :loading="loadingConnectorConfigIds.has(connectorId)" @click="loadConnectorConfig(connectorId)">重新读取</el-button>
      <el-button plain size="small" :loading="probingConnectorIds.has(connectorId)" :disabled="connectorProbeRequest.loading || probingConnectorIds.has(connectorId)" @click="probeConnectorItem(connectorId)">测试连接</el-button>
      <el-button type="primary" size="small" :loading="savingConnectorIds.has(connectorId)" @click="saveConnectorConfig(connectorId)">保存设置</el-button>
      <el-button plain size="small" :loading="connectorDeliveriesRequest.loading" @click="loadConnectorDeliveries(connectorId)">最近事件</el-button>
    </div>
    <div v-if="connectorProbeSnapshot(connectorId)" class="connector-probe-status">
      <el-tag size="small" :type="connectorProbeTagType(connectorProbeSnapshot(connectorId)!)">{{ connectorProbeStatusLabel(connectorProbeSnapshot(connectorId)!) }}</el-tag>
      <span v-if="connectorProbeSnapshot(connectorId)?.bridgeStatus">桥接状态：{{ connectorProbeSnapshot(connectorId)?.bridgeStatus }}</span>
      <details v-if="connectorProbeSnapshot(connectorId)?.statusCode || connectorProbeSnapshot(connectorId)?.errorCode" class="inline-diagnostic-details">
        <summary>查看连接诊断</summary>
        <span v-if="connectorProbeSnapshot(connectorId)?.statusCode">服务响应 {{ connectorProbeSnapshot(connectorId)?.statusCode }}</span>
        <span v-if="connectorProbeSnapshot(connectorId)?.errorCode" class="connector-probe-error">错误码：{{ connectorProbeSnapshot(connectorId)?.errorCode }}</span>
      </details>
    </div>
    <div v-if="connectorRecoverySnapshot(connectorId)" class="connector-recovery-telemetry">
      <span>恢复扫描 {{ connectorRecoverySnapshot(connectorId)?.runs ?? 0 }} 次</span>
      <span>检查 {{ connectorRecoverySnapshot(connectorId)?.inspected ?? 0 }} 条</span>
      <span>恢复 {{ connectorRecoverySnapshot(connectorId)?.recovered ?? 0 }} 条</span>
      <span>失败 {{ connectorRecoverySnapshot(connectorId)?.failed ?? 0 }} 条</span>
      <span>最近扫描 {{ formatRecoveryTime(connectorRecoverySnapshot(connectorId)?.lastRunAt) }}</span>
      <span v-if="connectorRecoverySnapshot(connectorId)?.lastError" class="connector-recovery-error">{{ connectorRecoverySnapshot(connectorId)?.lastError }}</span>
    </div>
    <div v-if="connectorDeliveryRows(connectorId).length" class="connector-delivery-list">
      <div v-for="delivery in connectorDeliveryRows(connectorId).slice(0, 5)" :key="delivery.deliveryKey" class="connector-delivery-item">
        <div>
          <strong>{{ connectorDeliveryStatusLabel(delivery.status) }}</strong>
          <span>尝试 {{ delivery.attemptCount }} 次</span>
          <small v-if="delivery.lastError">{{ delivery.lastError }}</small>
          <details class="inline-diagnostic-details" v-if="delivery.eventId">
            <summary>查看事件编号</summary>
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
          重投
        </el-button>
        <el-button
          v-if="delivery.cancellable"
          type="danger"
          link
          size="small"
          :loading="cancellingEventIds.has(delivery.eventId)"
          @click="cancelConnectorEventItem(connectorId, delivery.eventId)"
        >
          取消处理
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
            确认已送达
          </el-button>
          <el-button
            type="warning"
            link
            size="small"
            :loading="resolvingEventIds.has(delivery.eventId)"
            :disabled="resolvingEventIds.has(delivery.eventId)"
            @click="resolveConnectorEventItem(connectorId, delivery.eventId, 'failed')"
          >
            确认未送达
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
