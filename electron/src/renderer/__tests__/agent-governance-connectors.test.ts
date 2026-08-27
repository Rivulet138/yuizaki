import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const panelSource = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/system/views/AgentGovernancePanel.vue'),
  'utf8',
)

describe('Agent governance connector contract', () => {
  it('renders the connector registry as an operational status surface', () => {
    expect(panelSource).toContain('连接器状态')
    expect(panelSource).toContain('connectorRows')
    expect(panelSource).toContain('connector.state')
    expect(panelSource).toContain('connector.permissionScope')
    expect(panelSource).toContain('connector.capabilities')
    expect(panelSource).toContain('connector.dataFlow')
    expect(panelSource).toContain('connectorMutationError')
  })

  it('keeps planned adapters visible as uninstalled and disables unsupported actions', () => {
    expect(panelSource).toContain('未安装')
    expect(panelSource).toContain('v-if="connector.canDisable && connector.state !== \'disabled\'"')
    expect(panelSource).toContain('disableConnectorItem(connector.id)')
  })

  it('refreshes connector state with governance and extension snapshots', () => {
    expect(panelSource).toContain('loadConnectors()')
    expect(panelSource).toContain('connectorsRequest.loading')
    expect(panelSource).toContain('disableConnectorRequest.error')
  })

  it('provides direct redacted configuration for supported message adapters', () => {
    expect(panelSource).toContain('connectorDisplayName')
    expect(panelSource).toContain("telegram: 'Telegram'")
    expect(panelSource).toContain("discord: 'Discord'")
    expect(panelSource).toContain("qq: 'QQ 个人账号兼容桥'")
    expect(panelSource).toContain("wechat: '微信个人账号兼容桥'")
    expect(panelSource).toContain('Bot Token；留空表示不修改')
    expect(panelSource).toContain('可选 Bot Token；Interaction 过期后用于频道降级')
    expect(panelSource).toContain('降级 Bot Token')
    expect(panelSource).toContain('Webhook Secret（启用必填）；留空不修改')
    expect(panelSource).toContain('v-if="connectorId === \'telegram\'" class="connector-secret-row"')
    expect(panelSource).toContain('桥接令牌（启用必填）')
    expect(panelSource).toContain('clearConnectorSecret')
    expect(panelSource).toContain('clearBotToken')
    expect(panelSource).toContain('botTokenConfigured')
    expect(panelSource).toContain('publicKeyConfigured')
    expect(panelSource).toContain('个人账号兼容桥')
    expect(panelSource).not.toContain('App Secret')
    expect(panelSource).toContain('systemClient.updateConnectorConfig')
    expect(panelSource).toContain('systemClient.unbindConnectorAccount')
    expect(panelSource).toContain('清除桥接配置')
    expect(panelSource).toContain("draft.bridgeUrl = result.config.bridgeUrl || ''")
    expect(panelSource).toContain('保存设置')
  })

  it('shows recent delivery state and retries only persisted replies', () => {
    expect(panelSource).toContain('最近事件')
    expect(panelSource).toContain('delivery.attemptCount')
    expect(panelSource).toContain('delivery.lastError')
    expect(panelSource).toContain('delivery.retryable')
    expect(panelSource).toContain('retryConnectorDelivery')
    expect(panelSource).toContain('重投')
    expect(panelSource).toContain("processing: '处理中'")
    expect(panelSource).toContain("sending: '发送中（取消过晚）'")
    expect(panelSource).toContain("failed: '待重投'")
    expect(panelSource).toContain('delivery.cancellable')
    expect(panelSource).toContain('cancelConnectorEvent')
    expect(panelSource).toContain('取消处理')
    expect(panelSource).toContain('Webhook Secret（启用必填）')
  })
})
