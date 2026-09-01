<template>
  <PanelShell title="权限审计" tone="admin">
    <div class="governance-console">
      <section class="governance-toolbar" aria-label="治理操作">
        <div>
          <strong>{{ governancePosture }}</strong>
        </div>
        <div class="toolbar-actions">
          <el-tag :type="governancePostureTagType">{{ governancePosture }}</el-tag>
          <el-button type="primary" :loading="refreshing" @click="refreshGovernance">刷新治理快照</el-button>
        </div>
      </section>

      <nav class="governance-view-nav" aria-label="权限视图" role="tablist">
        <button
          v-for="view in governanceViews"
          :key="view.id"
          type="button"
          role="tab"
          class="governance-view-button"
          :class="{ active: activeGovernanceView === view.id }"
          :aria-selected="activeGovernanceView === view.id"
          @click="activeGovernanceView = view.id"
        >
          {{ view.label }}
        </button>
      </nav>

      <el-card v-show="activeGovernanceView === 'connectors'" class="panel-card connector-card" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <strong>连接器状态</strong>
              <span>{{ connectorSummary.running }} 个运行中 · {{ connectorSummary.uninstalled }} 个未安装 · {{ connectorSummary.failures }} 个故障</span>
            </div>
            <el-button plain size="small" :loading="connectorsRequest.loading" @click="loadConnectors">刷新连接器</el-button>
          </div>
        </template>
        <AsyncState :loading="connectorsRequest.loading" :error="connectorsRequest.error" :show-retry="false">
          <el-alert v-if="connectorMutationError" class="panel-alert" :title="connectorMutationError" type="error" show-icon :closable="false" />
          <div v-if="connectorRows.length" class="connector-list">
            <article v-for="connector in connectorRows" :key="connector.id" class="connector-item" :class="`connector-${connector.state}`">
              <div class="connector-main">
                <div>
                  <strong>{{ connector.name }}</strong>
                  <span>{{ connector.kind }} · {{ connector.permissionScope }}</span>
                </div>
                <el-tag size="small" :type="connectorTagType(connector.state)">{{ connectorStateLabel(connector.state) }}</el-tag>
              </div>
              <p>{{ connector.message }}</p>
              <div class="connector-meta">
                <span>能力：{{ connector.capabilities.join('、') }}</span>
                <span>数据流：{{ connector.dataFlow.join('；') }}</span>
                <span v-if="connector.readiness">资格：{{ connectorReadinessLabel(connector.readiness) }}</span>
              </div>
              <div class="connector-footer">
                <small v-if="connector.experimental">实验性，默认不启用</small>
                <small v-else>{{ connector.source === 'mcp' ? 'MCP 服务' : 'Agent 插件' }}</small>
                <el-button
                  v-if="connector.canDisable && connector.state !== 'disabled'"
                  type="danger"
                  link
                  size="small"
                  :loading="disablingConnectorIds.has(connector.id)"
                  :disabled="disablingConnectorIds.has(connector.id)"
                  @click="disableConnectorItem(connector.id)"
                >
                  一键停用
                </el-button>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无连接器状态" :image-size="64" />
          <el-tabs v-model="activeConnectorId" class="connector-config-tabs">
            <el-tab-pane v-for="connectorId in messageConnectorIds" :key="connectorId" :label="connectorDisplayName(connectorId)" :name="connectorId" lazy>
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
                <div class="connector-bridge-box">
                  <el-alert title="仅支持个人账号兼容桥。桥接程序由用户自行运行，掉线、封号和协议变更风险由用户自行承担。" type="warning" :closable="false" show-icon />
                  <div class="connector-secret-row">
                    <el-input v-model="connectorDrafts[connectorId].bridgeUrl" placeholder="兼容桥地址，例如 http://127.0.0.1:3000" />
                    <el-input v-model="connectorDrafts[connectorId].bridgeToken" type="password" show-password placeholder="桥接令牌（启用必填）" />
                  </div>
                  <div class="connector-config-actions">
                    <el-select v-model="connectorDrafts[connectorId].bridgeProtocol" size="small" placeholder="桥协议">
                      <el-option label="通用桥 API" value="generic" />
                      <el-option v-if="connectorId === 'qq'" label="OneBot 11" value="onebot11" />
                      <el-option v-if="connectorId === 'qq'" label="OneBot 12" value="onebot12" />
                    </el-select>
                    <el-button type="primary" size="small" :loading="accountBusyIds.has(connectorId)" @click="loginPersonalAccount(connectorId)">开始登录</el-button>
                    <el-button plain size="small" :loading="accountBusyIds.has(connectorId)" @click="refreshPersonalAccount(connectorId)">刷新状态</el-button>
                    <el-button type="danger" plain size="small" :disabled="accountBusyIds.has(connectorId)" @click="logoutPersonalAccount(connectorId)">退出账号</el-button>
                    <el-button type="danger" link size="small" :disabled="accountBusyIds.has(connectorId)" @click="unbindPersonalAccount(connectorId)">清除桥接配置</el-button>
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
                <span v-if="connectorProbeSnapshot(connectorId)?.statusCode">HTTP {{ connectorProbeSnapshot(connectorId)?.statusCode }}</span>
                <span v-if="connectorProbeSnapshot(connectorId)?.bridgeStatus">桥接状态：{{ connectorProbeSnapshot(connectorId)?.bridgeStatus }}</span>
                <span v-if="connectorProbeSnapshot(connectorId)?.errorCode" class="connector-probe-error">错误码：{{ connectorProbeSnapshot(connectorId)?.errorCode }}</span>
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
                    <strong>{{ delivery.eventId }}</strong>
                    <span>{{ connectorDeliveryStatusLabel(delivery.status) }} · 尝试 {{ delivery.attemptCount }} 次</span>
                    <small v-if="delivery.lastError">{{ delivery.lastError }}</small>
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
            </el-tab-pane>
          </el-tabs>
        </AsyncState>
      </el-card>

      <section v-show="activeGovernanceView === 'mcp' || activeGovernanceView === 'permissions'" class="governance-grid" :class="{ 'single-view': activeGovernanceView === 'permissions' }">
        <el-card v-show="activeGovernanceView === 'mcp'" class="panel-card mcp-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>MCP 服务</strong>
                <span>{{ connectedMcpCount }} / {{ mcpRows.length }} 个连接可用</span>
              </div>
              <div class="action-row">
                <el-button plain size="small" :loading="mcpRequest.loading" @click="loadMcp">刷新</el-button>
              </div>
            </div>
          </template>
          <AsyncState :loading="mcpRequest.loading" :error="mcpRequest.error" :show-retry="false">
            <el-alert
              v-if="mcpMutationError"
              class="panel-alert"
              :title="mcpMutationError"
              type="error"
              show-icon
              :closable="false"
            />
            <div v-if="mcpRows.length" class="mcp-filter-row" role="tablist" aria-label="MCP 服务筛选">
              <button
                v-for="option in mcpFilterOptions"
                :key="option.value"
                type="button"
                class="mcp-filter-button"
                :class="{ active: mcpFilter === option.value }"
                @click="mcpFilter = option.value"
              >
                <span>{{ option.label }}</span>
                <strong>{{ option.count }}</strong>
              </button>
            </div>
            <div v-if="filteredMcpRows.length" class="server-list">
              <article v-for="row in filteredMcpRows" :key="row.name" class="server-card" :class="serverTone(row)">
                <div class="server-main">
                  <div class="server-status-dot" :class="row.connected ? 'online' : 'offline'"></div>
                  <div class="server-title">
                    <strong>{{ row.name }}</strong>
                    <span>{{ mcpEndpointLabel(row) }}</span>
                  </div>
                  <el-tag :type="mcpRowTagType(row)" size="small">{{ mcpRowStatusLabel(row) }}</el-tag>
                </div>
                <div class="server-inventory">
                  <el-tag size="small" type="success" :title="formatInventoryNames(row.tools)">工具 {{ row.tools_count }}</el-tag>
                  <el-tag size="small" type="info" :title="formatInventoryNames(row.resources)">资源 {{ row.resources_count }}</el-tag>
                  <el-tag size="small" type="warning" :title="formatInventoryNames(row.prompts)">Prompt {{ row.prompts_count }}</el-tag>
                  <el-tag v-if="row.inventory_error" size="small" type="danger" :title="row.inventory_error">库存异常</el-tag>
                </div>
                <div class="server-meta">
                  <span>传输：{{ transportLabel(row.transport) }}</span>
                  <span>调用 {{ row.total_calls ?? 0 }}</span>
                  <span>失败 {{ row.total_failures ?? 0 }}</span>
                  <span>待处理 {{ row.pending_requests ?? 0 }}</span>
                  <span v-if="row.env_keys?.length">环境变量 {{ row.env_keys.join(', ') }}</span>
                  <span v-if="row.header_keys?.length">请求头 {{ row.header_keys.join(', ') }}</span>
                </div>
                <div class="server-footer">
                  <el-switch
                    :model-value="row.enabled"
                    size="small"
                    :disabled="togglingMcpNames.has(row.name) || removingMcpNames.has(row.name)"
                    @change="(value) => toggleMcpItem(row.name, Boolean(value))"
                  />
                  <div class="action-row">
                    <el-button
                      type="primary"
                      link
                      size="small"
                      :loading="refreshingMcpNames.has(row.name)"
                      :disabled="refreshingMcpNames.has(row.name) || removingMcpNames.has(row.name)"
                      @click="refreshMcpItem(row.name)"
                    >
                      重连
                    </el-button>
                    <el-button
                      type="danger"
                      link
                      size="small"
                      :loading="removingMcpNames.has(row.name)"
                      :disabled="removingMcpNames.has(row.name)"
                      @click="removeMcpItem(row.name)"
                    >
                      删除
                    </el-button>
                  </div>
                </div>
                <div class="history-strip">
                  <div v-for="entry in recentMcpHistory(row.history).slice(0, 3)" :key="`${row.name}-${entry.timestamp}-${entry.event}-${entry.request_id || ''}`" class="history-chip">
                    <el-tag size="small" :type="mcpHistoryTagType(entry.status)">{{ mcpHistoryStatusLabel(entry.status) }}</el-tag>
                    <span>{{ entry.event }}</span>
                    <small>{{ formatMcpTimestamp(entry.timestamp) }}</small>
                  </div>
                  <span v-if="!row.history.length" class="empty-inline">暂无连接历史</span>
                </div>
              </article>
            </div>
            <el-empty v-else :description="mcpEmptyDescription" :image-size="72" />
          </AsyncState>
        </el-card>

        <aside class="side-stack">
          <el-card v-show="activeGovernanceView === 'mcp'" class="panel-card register-card" shadow="never">
            <template #header>
              <div class="card-head compact">
                <div>
                  <strong>新增 MCP 服务器</strong>
                </div>
                <el-tag type="primary">{{ transportLabel(mcpForm.transport) }}</el-tag>
              </div>
            </template>
            <div v-if="mcpPresets.length" class="preset-grid">
              <article v-for="preset in mcpPresets" :key="preset.id" class="preset-card" :class="{ installed: preset.installed }">
                <div>
                  <strong>{{ preset.name }}</strong>
                  <span>{{ preset.description }}</span>
                </div>
                <div class="preset-meta">
                  <el-tag size="small" type="info">{{ presetCategoryLabel(preset.category) }}</el-tag>
                  <el-tag size="small" type="primary">{{ transportLabel(preset.transport) }}</el-tag>
                  <el-tag v-if="preset.env_keys?.length" size="small" type="warning">{{ preset.env_keys.length }} 个环境变量</el-tag>
                  <el-tag v-if="preset.header_keys?.length" size="small" type="danger">{{ preset.header_keys.length }} 个请求头</el-tag>
                </div>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :disabled="preset.installed"
                  :loading="installMcpPresetRequest.loading"
                  @click="installPreset(preset.id)"
                >
                  {{ preset.installed ? '已安装' : '安装' }}
                </el-button>
              </article>
            </div>
            <el-alert v-if="installMcpPresetRequest.error" class="panel-alert" :title="installMcpPresetRequest.error" type="error" show-icon :closable="false" />
            <div class="form-grid">
              <el-input v-model="mcpForm.name" size="small" placeholder="服务标识名，例如 fetch" />
              <el-select v-model="mcpForm.transport" size="small">
                <el-option label="HTTP" value="http" />
                <el-option label="SSE" value="sse" />
                <el-option label="STDIO" value="stdio" />
                <el-option label="流式 HTTP" value="streamable_http" />
              </el-select>
              <el-input v-if="mcpForm.transport !== 'stdio'" v-model="mcpForm.base_url" size="small" class="wide" placeholder="服务地址 URL" />
              <template v-else>
                <el-input v-model="mcpForm.command" size="small" placeholder="命令，例如 npx / python" />
                <el-input v-model="mcpForm.args_text" size="small" placeholder='参数 JSON，例如 ["--config","E:\\My App\\mcp.json"]' />
              </template>
              <el-input v-model="mcpForm.env_text" size="small" class="wide" placeholder='环境变量 JSON，例如 {"FIRECRAWL_API_KEY":"{env:FIRECRAWL_API_KEY}"}' />
              <el-input v-model="mcpForm.headers_text" size="small" class="wide" placeholder='请求头 JSON，例如 {"Authorization":"Bearer {env:TOKEN}"}' />
            </div>
            <el-alert v-if="addMcpRequest.error" class="panel-alert" :title="addMcpRequest.error" type="error" show-icon :closable="false" />
            <div class="submit-row">
              <el-button type="primary" :disabled="!canSubmitMcp" :loading="addMcpRequest.loading" @click="submitMcp">注册并刷新</el-button>
            </div>
          </el-card>

          <el-card v-show="activeGovernanceView === 'permissions'" class="panel-card permission-card" shadow="never">
            <template #header>
              <div class="card-head compact">
                <div>
                  <strong>{{ permissionRows.length }} 条已记住规则</strong>
                </div>
                <div class="action-row">
                  <el-button plain size="small" :loading="permissionsRequest.loading" @click="loadPermissions">刷新</el-button>
                  <el-button size="small" type="danger" :disabled="permissionRows.length === 0" :loading="clearPermissionsRequest.loading" @click="clearAllPermissions">清空</el-button>
                </div>
              </div>
            </template>
            <AsyncState :loading="permissionsRequest.loading" :error="permissionsRequest.error" :show-retry="false">
              <el-alert
                v-if="permissionMutationError"
                class="panel-alert"
                :title="permissionMutationError"
                type="error"
                show-icon
                :closable="false"
              />
              <div v-if="permissionRows.length" class="permission-list">
                <article v-for="row in permissionRows" :key="row.key" class="permission-item" :class="row.approved ? 'approved' : 'denied'">
                  <div>
                    <strong>{{ row.key }}</strong>
                    <span>{{ capabilityLabel(row.capabilityType, row.capabilityKind) }} · 风险 {{ riskLabel(row.riskLevel) }}</span>
                  </div>
                  <el-button
                    type="danger"
                    link
                    size="small"
                    :loading="revokingPermissionKeys.has(row.key)"
                    :disabled="revokingPermissionKeys.has(row.key)"
                    @click="revokePermissionItem(row.key)"
                  >
                    撤销
                  </el-button>
                </article>
              </div>
              <el-empty v-else description="暂无审批记录" :image-size="60" />
            </AsyncState>
          </el-card>
        </aside>
      </section>

      <section v-show="activeGovernanceView === 'extensions' || activeGovernanceView === 'permissions'" class="governance-grid lower-grid single-view">
        <el-card v-show="activeGovernanceView === 'extensions'" class="panel-card extension-card" shadow="never">
          <template #header>
            <div class="card-head">
              <div>
                <strong>扩展宿主</strong>
                <span>Agent / Electron / MCP</span>
              </div>
              <el-button plain size="small" :loading="agentPluginsRequest.loading" @click="refreshExtensions">刷新扩展</el-button>
            </div>
          </template>
          <AsyncState :loading="extensionLoading" :error="extensionError" :show-retry="false">
            <div class="host-grid">
              <article v-for="host in extensionHosts" :key="host.label" class="host-card" :class="host.tone">
                <span>{{ host.label }}</span>
                <strong>{{ host.value }}</strong>
                <small>{{ host.detail }}</small>
              </article>
            </div>
            <el-alert v-if="agentPluginMutationError" class="panel-alert" :title="agentPluginMutationError" type="error" show-icon :closable="false" />
            <div v-if="agentPluginRows.length" class="agent-plugin-list" aria-label="Agent 插件运行配置">
              <article v-for="plugin in agentPluginRows" :key="plugin.id" class="agent-plugin-item" :class="{ disabled: !plugin.enabled, broken: plugin.error }">
                <div class="agent-plugin-main">
                  <div>
                    <strong>{{ plugin.name || plugin.id }}</strong>
                    <span>{{ plugin.id }}<template v-if="plugin.version"> · {{ plugin.version }}</template></span>
                  </div>
                  <div class="action-row">
                    <el-tag size="small" :type="plugin.loaded ? 'success' : plugin.error ? 'danger' : 'info'">{{ plugin.loaded ? '已加载' : plugin.error ? '异常' : '未加载' }}</el-tag>
                    <el-switch
                      :model-value="plugin.enabled"
                      size="small"
                      :disabled="togglingAgentPluginIds.has(plugin.id)"
                      @change="(value) => toggleAgentPluginItem(plugin.id, Boolean(value))"
                    />
                  </div>
                </div>
                <el-alert v-if="plugin.error" class="plugin-error" :title="plugin.error" type="error" show-icon :closable="false" />
                <div class="plugin-config-row">
                  <el-input
                    v-model="pluginConfigDrafts[plugin.id]"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 6 }"
                    resize="vertical"
                    spellcheck="false"
                  />
                  <el-button size="small" type="primary" plain :loading="updateAgentPluginConfigRequest.loading" @click="saveAgentPluginConfig(plugin.id)">保存配置</el-button>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无 Agent 插件" :image-size="60" />
            <div class="contribution-matrix">
              <div class="matrix-head">贡献类型</div>
              <div>Electron 插件</div>
              <div>Agent 插件</div>
              <div>MCP</div>
              <template v-for="row in contributionComparisonRows" :key="row.category">
                <div class="matrix-category">{{ contributionCategoryLabel(row.category) }}</div>
                <div>{{ row.electron }}</div>
                <div>{{ row.agent }}</div>
                <div>{{ row.mcp }}</div>
              </template>
            </div>
          </AsyncState>
        </el-card>

        <el-card v-show="activeGovernanceView === 'permissions'" class="panel-card audit-card" shadow="never">
          <template #header>
            <div class="card-head compact">
              <div>
                <strong>{{ permissionAuditRows.length }} 条事件</strong>
              </div>
              <el-tag :type="permissionAuditRows.length ? 'warning' : 'success'">{{ permissionAuditRows.length ? '可追踪' : '暂无事件' }}</el-tag>
            </div>
          </template>
          <AsyncState :loading="permissionsRequest.loading" :error="permissionsRequest.error" :show-retry="false">
            <div v-if="permissionAuditRows.length" class="audit-timeline">
              <article v-for="item in permissionAuditRows.slice(0, 8)" :key="`${item.timestamp}-${item.capability_id || item.tool_name || item.decision}`" class="audit-item">
                <div class="audit-dot"></div>
                <div>
                  <strong>{{ permissionAuditTitle(item) }}</strong>
                  <span>{{ formatMcpTimestamp(item.timestamp) }} · {{ decisionLabel(item.decision) }} · 风险 {{ riskLabel(item.risk_level) }}</span>
                </div>
              </article>
            </div>
            <el-empty v-else description="暂无审批审计事件" :image-size="60" />
          </AsyncState>
        </el-card>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { onMounted, reactive, computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { systemClient } from '@/api/client'
import { useSystemDomain } from '../composables/useSystemDomain'
import { usePluginDomain } from '../../plugin/composables/usePluginDomain'
import type { ConnectorProbeSnapshot, ConnectorState, ConnectorStatus, MCPHistoryEntry, MCPInventoryItem, MCPServerConfigSnapshot, MCPServerPresetSnapshot, MCPServerStatusSnapshot, MessageConnectorConfigSnapshot, MessageConnectorConfigUpdate, PermissionAuditRecord, RuntimeContributionSummary } from '@/../shared/agent'
import type { PluginContributionSummary } from '@/../shared/plugin'

type GovernanceViewId = 'connectors' | 'mcp' | 'permissions' | 'extensions'

const governanceViews: Array<{ id: GovernanceViewId; label: string }> = [
  { id: 'connectors', label: '连接器' },
  { id: 'mcp', label: 'MCP' },
  { id: 'permissions', label: '授权' },
  { id: 'extensions', label: '扩展' },
]
const activeGovernanceView = ref<GovernanceViewId>('connectors')

const {
  permissions,
  mcp,
  agentPlugins,
  permissionsRequest,
  revokePermissionRequest,
  clearPermissionsRequest,
  mcpRequest,
  toggleMcpRequest,
  addMcpRequest,
  installMcpPresetRequest,
  removeMcpRequest,
  refreshMcpRequest,
  agentPluginsRequest,
  connectors,
  connectorsRequest,
  disableConnectorRequest,
  toggleAgentPluginRequest,
  updateAgentPluginConfigRequest,
  loadPermissions,
  revokePermission,
  clearPermissions,
  loadMcp,
  toggleMcp,
  addMcp,
  installMcpPreset,
  removeMcp,
  refreshMcp,
  loadAgentPlugins,
  loadConnectors,
  connectorDeliveries,
  connectorRecovery,
  connectorAccounts,
  connectorProbes,
  loadConnectorAccount,
  loginConnectorAccount,
  refreshConnectorAccount,
  logoutConnectorAccount,
  connectorDeliveriesRequest,
  connectorProbeRequest,
  cancelConnectorEventRequest,
  resolveConnectorEventRequest,
  loadConnectorDeliveries,
  retryConnectorDelivery,
  cancelConnectorEvent,
  resolveConnectorEvent,
  probeConnector,
  disableConnector,
  toggleAgentPlugin,
  updateAgentPluginConfig,
} = useSystemDomain()

const {
  payload: electronPluginSnapshot,
  pluginsRequest,
  loadPlugins: loadElectronPlugins,
} = usePluginDomain()

const mcpForm = reactive({
  name: '',
  base_url: '',
  command: '',
  args_text: '',
  env_text: '',
  headers_text: '',
  transport: 'http',
  enabled: true,
})
const pluginConfigDrafts = reactive<Record<string, string>>({})
const removingMcpNames = ref(new Set<string>())
const togglingMcpNames = ref(new Set<string>())
const refreshingMcpNames = ref(new Set<string>())
const revokingPermissionKeys = ref(new Set<string>())
const togglingAgentPluginIds = ref(new Set<string>())
const disablingConnectorIds = ref(new Set<string>())
const loadingConnectorConfigIds = ref(new Set<string>())
const savingConnectorIds = ref(new Set<string>())
const retryingDeliveryKeys = ref(new Set<string>())
const accountBusyIds = ref(new Set<string>())
const probingConnectorIds = ref(new Set<string>())
const messageConnectorIds = ['telegram', 'discord', 'qq', 'wechat'] as const
type MessageConnectorId = typeof messageConnectorIds[number]
const activeConnectorId = ref<MessageConnectorId>('telegram')
const connectorConfigs = reactive<Partial<Record<MessageConnectorId, MessageConnectorConfigSnapshot>>>({})
type ConnectorDraft = MessageConnectorConfigUpdate & { botToken: string; webhookSecret: string; publicKey: string; accountMode: string; bridgeUrl: string; bridgeProtocol: string; bridgeToken: string; clearBotToken: boolean; clearWebhookSecret: boolean; clearPublicKey: boolean; clearBridgeUrl: boolean; clearBridgeProtocol: boolean; clearBridgeToken: boolean }
const newConnectorDraft = (): ConnectorDraft => ({ enabled: false, botToken: '', webhookSecret: '', publicKey: '', accountMode: 'personal_bridge', bridgeUrl: '', bridgeProtocol: 'generic', bridgeToken: '', clearBotToken: false, clearWebhookSecret: false, clearPublicKey: false, clearBridgeUrl: false, clearBridgeProtocol: false, clearBridgeToken: false })
const connectorDrafts = reactive<Record<MessageConnectorId, ConnectorDraft>>({
  telegram: newConnectorDraft(),
  discord: newConnectorDraft(),
  qq: newConnectorDraft(),
  wechat: newConnectorDraft(),
})
const mcpFilter = ref<MCPFilter>('all')

const addPending = (setRef: { value: Set<string> }, key: string) => {
  setRef.value = new Set(setRef.value).add(key)
}

const removePending = (setRef: { value: Set<string> }, key: string) => {
  const next = new Set(setRef.value)
  next.delete(key)
  setRef.value = next
}

type MCPRow = MCPServerConfigSnapshot & MCPServerStatusSnapshot & {
  name: string
  statusText: string
  history: MCPHistoryEntry[]
  tools_count: number
  resources_count: number
  prompts_count: number
  tools: MCPInventoryItem[]
  resources: MCPInventoryItem[]
  prompts: MCPInventoryItem[]
}

type MCPFilter = 'all' | 'connected' | 'error' | 'disabled'

interface MCPFilterOption {
  value: MCPFilter
  label: string
  count: number
}

const mcpRows = computed<MCPRow[]>(() => {
  if (!mcp.value) return []
  return Object.entries(mcp.value.servers).map(([name, server]) => {
    const status = mcp.value?.status?.[name]
    return {
      name,
      ...server,
      ...(status || {}),
      enabled: status?.enabled ?? server.enabled,
      transport: status?.transport || server.transport,
      statusText: status?.message || (status?.ok ? 'ok' : 'offline'),
      history: status?.history || [],
      tools: status?.tools || [],
      resources: status?.resources || [],
      prompts: status?.prompts || [],
      tools_count: status?.tools_count ?? status?.tools?.length ?? 0,
      resources_count: status?.resources_count ?? status?.resources?.length ?? 0,
      prompts_count: status?.prompts_count ?? status?.prompts?.length ?? 0,
    }
  })
})

const mcpContributionSummary = computed(() => mcp.value?.contributionSummary || [])
const mcpPresets = computed<MCPServerPresetSnapshot[]>(() => mcp.value?.presets || [])
const agentPluginRows = computed(() => agentPlugins.value?.plugins || [])
const agentPluginContributionSummary = computed(() => agentPlugins.value?.contributionSummary || [])
const electronPluginContributionSummary = computed(() => electronPluginSnapshot.value?.contributionSummary || [])
const permissionAuditRows = computed(() => [...(permissions.value?.audit || [])].reverse())
const connectorRows = computed<ConnectorStatus[]>(() => connectors.value?.connectors || [])
const connectorSummary = computed(() => connectors.value?.summary || {
  total: 0,
  installed: 0,
  enabled: 0,
  running: 0,
  failures: 0,
  uninstalled: 0,
  canDisable: 0,
})

const formatPluginConfig = (config?: Record<string, unknown>) => JSON.stringify(config ?? {}, null, 2)

watch(agentPluginRows, (rows) => {
  const activeIds = new Set(rows.map((plugin) => plugin.id))
  rows.forEach((plugin) => {
    if (pluginConfigDrafts[plugin.id] === undefined) {
      pluginConfigDrafts[plugin.id] = formatPluginConfig(plugin.config)
    }
  })
  Object.keys(pluginConfigDrafts).forEach((pluginId) => {
    if (!activeIds.has(pluginId)) {
      delete pluginConfigDrafts[pluginId]
    }
  })
}, { immediate: true })

type ContributionCategory = RuntimeContributionSummary['category']
type ContributionSummaryItem = RuntimeContributionSummary | PluginContributionSummary

const contributionCategories: ContributionCategory[] = ['ui', 'capability', 'event', 'policy']
const contributionCount = (items: readonly ContributionSummaryItem[], category: ContributionCategory) => items.find((item) => item.category === category)?.count || 0
const contributionComparisonRows = computed(() => contributionCategories.map((category) => ({
  category,
  electron: contributionCount(electronPluginContributionSummary.value, category),
  agent: contributionCount(agentPluginContributionSummary.value, category),
  mcp: contributionCount(mcpContributionSummary.value, category),
})))

const refreshing = computed(() => mcpRequest.loading || permissionsRequest.loading || agentPluginsRequest.loading || pluginsRequest.loading || connectorsRequest.loading)
const extensionLoading = computed(() => agentPluginsRequest.loading || pluginsRequest.loading || mcpRequest.loading || connectorsRequest.loading)
const extensionError = computed(() => agentPluginsRequest.error || pluginsRequest.error || mcpRequest.error)
const mcpMutationError = computed(() => toggleMcpRequest.error || refreshMcpRequest.error || removeMcpRequest.error || installMcpPresetRequest.error)
const permissionMutationError = computed(() => revokePermissionRequest.error || clearPermissionsRequest.error)
const agentPluginMutationError = computed(() => toggleAgentPluginRequest.error || updateAgentPluginConfigRequest.error)
const connectorMutationError = computed(() => disableConnectorRequest.error)
const connectedMcpCount = computed(() => mcpRows.value.filter((row) => row.connected).length)
const failingMcpCount = computed(() => mcpRows.value.filter((row) => row.enabled && !row.connected).length)
const disabledMcpCount = computed(() => mcpRows.value.filter((row) => !row.enabled).length)
const mcpFilterOptions = computed<MCPFilterOption[]>(() => [
  { value: 'all', label: '全部', count: mcpRows.value.length },
  { value: 'connected', label: '已连接', count: connectedMcpCount.value },
  { value: 'error', label: '需处理', count: failingMcpCount.value },
  { value: 'disabled', label: '未启用', count: disabledMcpCount.value },
])
const filteredMcpRows = computed(() => mcpRows.value.filter((row) => {
  if (mcpFilter.value === 'connected') return row.connected
  if (mcpFilter.value === 'error') return row.enabled && !row.connected
  if (mcpFilter.value === 'disabled') return !row.enabled
  return true
}))
const mcpEmptyDescription = computed(() => {
  if (!mcpRows.value.length) return '暂无 MCP 服务器配置'
  const selected = mcpFilterOptions.value.find((item) => item.value === mcpFilter.value)
  return `没有${selected?.label || '当前'} MCP 服务`
})

const connectorStateLabel = (state: ConnectorState) => {
  const labels: Record<ConnectorState, string> = {
    running: '运行中',
    disabled: '已停用',
    failure: '故障',
    uninstalled: '未安装',
  }
  return labels[state]
}

const connectorReadinessLabel = (readiness: ConnectorStatus['readiness']) => {
  if (!readiness) return '未提供'
  if (readiness.status === 'ready_for_staging') return readiness.requiresPublicHttps ? '配置完整，仍需公网 HTTPS 验证' : '配置完整，仍需桥接可达性验证'
  if (readiness.status === 'not_qualified') return readiness.reasons[0]?.detail || '未达到 staging 条件'
  return readiness.status
}

const connectorDisplayName = (connectorId: MessageConnectorId) => ({
  telegram: 'Telegram',
  discord: 'Discord',
  qq: 'QQ 个人账号兼容桥',
  wechat: '微信个人账号兼容桥',
}[connectorId])

const copyConnectorWebhookPath = async (connectorId: MessageConnectorId) => {
  const path = connectorConfigs[connectorId]?.webhookPath
  if (!path) return
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard_unavailable')
    await navigator.clipboard.writeText(path)
    ElMessage.success('回调路径已复制')
  } catch {
    ElMessage.warning('当前环境无法访问剪贴板，请手动复制回调路径')
  }
}

const connectorTagType = (state: ConnectorState): 'success' | 'info' | 'warning' | 'danger' => {
  if (state === 'running') return 'success'
  if (state === 'failure') return 'danger'
  if (state === 'disabled') return 'info'
  return 'warning'
}

const connectorDeliveryRows = (connectorId: MessageConnectorId) => connectorDeliveries.value[connectorId] || []
const connectorRecoverySnapshot = (connectorId: MessageConnectorId) => connectorRecovery.value[connectorId]
const refreshConnectorState = async (connectorId: MessageConnectorId) => {
  // Reconcile both the delivery projection and connector health after an operator action.
  await Promise.all([
    loadConnectorDeliveries(connectorId),
    loadConnectors(),
  ])
}
const formatRecoveryTime = (timestamp: number | null | undefined) => {
  if (!timestamp || !Number.isFinite(timestamp)) return '尚未扫描'
  return new Date(timestamp * 1000).toLocaleString()
}
const connectorDeliveryStatusLabel = (status: string) => ({
  delivered: '已送达',
  processing: '处理中',
  sending: '发送中（取消过晚）',
  failed: '待重投',
  unknown_effect: '外部结果未知（需人工确认）',
}[status] || status)

const connectorProbeSnapshot = (connectorId: MessageConnectorId) => connectorProbes.value[connectorId]
const connectorProbeStatusLabel = (snapshot: ConnectorProbeSnapshot) => {
  if (snapshot.status === 'reachable') return '连接可用'
  if (snapshot.status === 'signature_ready') return '仅签名校验就绪'
  if (snapshot.status === 'bridge_reachable') return '兼容桥可用'
  if (snapshot.status === 'provider_rejected') return '服务端拒绝'
  if (snapshot.status === 'unreachable') return '无法连接'
  return snapshot.status
}
const connectorProbeTagType = (snapshot: ConnectorProbeSnapshot): 'success' | 'info' | 'warning' | 'danger' => {
  if (snapshot.ok) return 'success'
  if (snapshot.status === 'signature_ready') return 'info'
  if (snapshot.status === 'provider_rejected') return 'warning'
  return 'danger'
}

const cancellingEventIds = ref(new Set<string>())
const resolvingEventIds = ref(new Set<string>())

const cancelConnectorEventItem = async (connectorId: MessageConnectorId, eventId: string) => {
  addPending(cancellingEventIds, eventId)
  try {
    const result = await cancelConnectorEvent(connectorId, eventId)
    if (result?.cancelled) ElMessage.success('事件处理已取消')
    else ElMessage.warning(cancelConnectorEventRequest.error || '取消过晚；回复可能已经发送')
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '取消状态未知；请刷新后检查')
  } finally {
    removePending(cancellingEventIds, eventId)
    await refreshConnectorState(connectorId).catch(() => undefined)
  }
}

const retryDeliveryItem = async (connectorId: MessageConnectorId, deliveryKey: string) => {
  addPending(retryingDeliveryKeys, deliveryKey)
  try {
    const result = await retryConnectorDelivery(connectorId, deliveryKey)
    if (result?.ok) ElMessage.success(result.alreadySent ? '该事件已送达' : '回复已重新投递')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重新投递失败')
  } finally {
    removePending(retryingDeliveryKeys, deliveryKey)
    await refreshConnectorState(connectorId).catch(() => undefined)
  }
}

const resolveConnectorEventItem = async (
  connectorId: MessageConnectorId,
  eventId: string,
  outcome: 'delivered' | 'failed',
) => {
  try {
    await ElMessageBox.confirm(
      outcome === 'delivered'
        ? '请先在外部平台确认这条回复已经出现，再将本地状态标记为已送达。'
        : '请确认外部平台没有收到这条回复。此操作不会自动再次发送。',
      outcome === 'delivered' ? '确认外部发送结果' : '确认未送达',
      {
        confirmButtonText: outcome === 'delivered' ? '标记已送达' : '标记未送达',
        cancelButtonText: '取消',
        type: outcome === 'delivered' ? 'info' : 'warning',
      },
    )
  } catch {
    return
  }
  addPending(resolvingEventIds, eventId)
  try {
    const result = await resolveConnectorEvent(connectorId, eventId, outcome)
    if (result?.ok) {
      ElMessage.success(result.alreadyResolved ? '事件状态已经收敛' : outcome === 'delivered' ? '已标记为送达' : '已标记为失败，可人工重投')
    } else {
      ElMessage.warning(resolveConnectorEventRequest.error || '状态未能收敛，请刷新后重试')
    }
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '状态未能收敛，请刷新后重试')
  } finally {
    removePending(resolvingEventIds, eventId)
    await refreshConnectorState(connectorId).catch(() => undefined)
  }
}

const probeConnectorItem = async (connectorId: MessageConnectorId, notify = true) => {
  addPending(probingConnectorIds, connectorId)
  try {
    const result = await probeConnector(connectorId)
    if (!notify) return result
    if (result?.ok) ElMessage.success(connectorProbeStatusLabel(result))
    else if (result) ElMessage.warning(connectorProbeStatusLabel(result))
    else if (connectorProbeRequest.error) ElMessage.error(connectorProbeRequest.error)
    return result
  } finally {
    removePending(probingConnectorIds, connectorId)
  }
}

const governancePosture = computed(() => {
  if (failingMcpCount.value > 0) return '需要复核 MCP 连接'
  if (mcpRows.value.length === 0 && permissionRows.value.length === 0) return '等待治理快照'
  return '治理面稳定'
})

const governancePostureTagType = computed(() => {
  if (failingMcpCount.value > 0) return 'danger'
  if (mcpRows.value.length === 0 && permissionRows.value.length === 0) return 'info'
  return 'success'
})

const extensionHosts = computed(() => [
  {
    label: 'Agent 插件',
    value: agentPluginRows.value.length,
    detail: `${agentPluginRows.value.filter((item) => item.enabled).length} 个已启用`,
    tone: 'blue',
  },
  {
    label: 'Electron 插件',
    value: electronPluginSnapshot.value?.plugins.length ?? 0,
    detail: `${electronPluginSnapshot.value?.plugins.filter((item) => item.enabled).length ?? 0} 个已启用`,
    tone: 'violet',
  },
  {
    label: 'MCP 贡献',
    value: mcpContributionSummary.value.reduce((total, item) => total + item.count, 0),
    detail: '来自外部上下文协议服务',
    tone: 'green',
  },
])

const recentMcpHistory = (history: MCPHistoryEntry[]) => [...history].reverse()
const formatMcpTimestamp = (timestamp: string) => timestamp.replace('T', ' ').slice(0, 19)

const mcpHistoryTagType = (status: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' => {
  if (status === 'ok' || status === 'enabled') return 'success'
  if (status === 'started' || status === 'pending' || status === 'closing') return 'warning'
  if (status === 'error' || status === 'failed') return 'danger'
  if (status === 'disabled' || status === 'closed' || status === 'removed') return 'info'
  return 'primary'
}

const mcpHistoryStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    ok: '成功',
    enabled: '启用',
    started: '启动',
    pending: '等待',
    closing: '关闭中',
    error: '错误',
    failed: '失败',
    disabled: '禁用',
    closed: '已关闭',
    removed: '已删除',
  }
  return labels[status] || status
}

const formatInventoryNames = (items?: MCPInventoryItem[] | null) => {
  if (!items?.length) return '未上报库存条目'
  return items.map((item) => item.description ? `${item.name}: ${item.description}` : item.name).join('\n')
}

const permissionRows = computed(() => {
  const remembered = permissions.value?.remembered || {}
  const audit = permissions.value?.audit || []
  return Object.entries(remembered).map(([key, approved]) => {
    const latest = [...audit].reverse().find((item) => (item.capability_id || item.tool_name) === key || `${item.tool_name || ''}::${item.remember_scope || 'default'}` === key)
    return {
      key,
      approved,
      capabilityType: latest?.capability_type || 'tool',
      capabilityKind: latest?.capability_kind || 'tool',
      riskLevel: latest?.risk_level || null,
    }
  })
})

const transportLabel = (transport: string) => {
  const labels: Record<string, string> = { http: 'HTTP', sse: 'SSE', stdio: 'STDIO', streamable_http: 'Streamable HTTP' }
  return labels[transport] || transport.toUpperCase()
}

const presetCategoryLabel = (category: string) => {
  const labels: Record<string, string> = {
    companion: '桌宠',
    daily: '日常',
    diagnostics: '诊断',
    browser: '浏览器',
    research: '调研',
    web: '网页',
    docs: '文档',
    code: '代码',
  }
  return labels[category] || category
}

const serverTone = (row: MCPRow) => {
  if (!row.enabled) return 'muted'
  if (row.connected) return 'healthy'
  return 'broken'
}

const mcpRowTagType = (row: MCPRow): 'success' | 'warning' | 'danger' | 'info' => {
  if (!row.enabled) return 'info'
  if (row.connected) return 'success'
  if (row.inventory_error) return 'warning'
  return 'danger'
}

const mcpRowStatusLabel = (row: MCPRow) => {
  if (!row.enabled) return '已禁用'
  if (row.connected) return '已连接'
  if (row.inventory_error) return '库存异常'
  return '离线'
}

const mcpEndpointLabel = (row: MCPRow) => row.transport === 'stdio' ? `${row.command || 'stdio'} ${(row.args || []).join(' ')}`.trim() : row.base_url

const isHttpMcpUrl = (value: string) => {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

const canSubmitMcp = computed(() => {
  if (!mcpForm.name.trim() || addMcpRequest.loading) return false
  if (mcpForm.transport === 'stdio') return Boolean(mcpForm.command.trim())
  return isHttpMcpUrl(mcpForm.base_url.trim())
})

const contributionCategoryLabel = (category: ContributionCategory) => {
  const labels: Record<ContributionCategory, string> = {
    ui: '界面入口',
    capability: '能力工具',
    event: '事件钩子',
    policy: '权限策略',
  }
  return labels[category]
}

const capabilityLabel = (type: string, kind: string) => `${type || 'tool'} / ${kind || 'tool'}`
const riskLabel = (risk?: string | null) => risk || '未知'

const decisionLabel = (decision: string) => {
  const labels: Record<string, string> = {
    approved: '已允许',
    allowed: '已允许',
    denied: '已拒绝',
    auto_allow: '自动允许',
    remembered_allow: '记住允许',
    remembered_deny: '记住阻断',
    remembered: '已记住',
    revoked: '已撤销',
    cleared: '已清空',
  }
  return labels[decision] || decision
}

const permissionAuditTitle = (item: PermissionAuditRecord) => item.capability_id || item.tool_name || item.capability_kind || '未命名能力'

const refreshGovernance = async () => {
  await Promise.all([
    loadPermissions(), loadMcp(), loadAgentPlugins(), loadElectronPlugins(), loadConnectors(), loadConnectorConfigs(),
    ...messageConnectorIds.map((connectorId) => loadConnectorDeliveries(connectorId)),
    loadConnectorAccount('qq'), loadConnectorAccount('wechat'),
  ])
}

const refreshExtensions = async () => {
  await Promise.all([loadAgentPlugins(), loadElectronPlugins(), loadMcp(), loadConnectors()])
}

onMounted(() => {
  void refreshGovernance()
})

const revokePermissionItem = async (toolName: string) => {
  addPending(revokingPermissionKeys, toolName)
  try {
    await revokePermission(toolName)
  } finally {
    removePending(revokingPermissionKeys, toolName)
  }
}

const clearAllPermissions = async () => {
  if (permissionRows.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `将清空 ${permissionRows.value.length} 条已记住的权限规则。之后工具调用会重新询问。`,
      '清空已记住权限',
      {
        confirmButtonText: '清空权限',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await clearPermissions()
}

const parseRecordJson = (value: string, label: string): Record<string, string> | undefined => {
  const trimmed = value.trim()
  if (!trimmed) return undefined
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    ElMessage.error(`${label} 必须是有效 JSON`)
    return undefined
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    ElMessage.error(`${label} 必须是 JSON 对象`)
    return undefined
  }
  return Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>)
      .filter(([key]) => key.trim())
      .map(([key, raw]) => [key, String(raw)]),
  )
}

const submitMcp = async () => {
  if (!mcpForm.name.trim()) {
    ElMessage.warning('请填写 MCP 服务标识名')
    return
  }
  if (!canSubmitMcp.value) {
    ElMessage.warning(mcpForm.transport === 'stdio' ? '请填写 STDIO 启动命令' : '请填写有效的 MCP 服务 URL')
    return
  }
  const env = parseRecordJson(mcpForm.env_text, '环境变量')
  if (mcpForm.env_text.trim() && !env) return
  const headers = parseRecordJson(mcpForm.headers_text, '请求头')
  if (mcpForm.headers_text.trim() && !headers) return
  let args: string[] | undefined
  if (mcpForm.args_text.trim()) {
    try {
      const parsed = JSON.parse(mcpForm.args_text)
      if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== 'string')) {
        throw new Error('invalid_args')
      }
      args = parsed
    } catch {
      ElMessage.error('参数必须是 JSON 字符串数组')
      return
    }
  }
  const result = await addMcp({
    name: mcpForm.name.trim(),
    base_url: mcpForm.base_url.trim(),
    command: mcpForm.command.trim() || undefined,
    args,
    transport: mcpForm.transport,
    enabled: mcpForm.enabled,
    env,
    headers,
  })
  if (result?.ok) {
    mcpForm.name = ''
    mcpForm.base_url = ''
    mcpForm.command = ''
    mcpForm.args_text = ''
    mcpForm.env_text = ''
    mcpForm.headers_text = ''
  }
}

const installPreset = async (presetId: string) => {
  const result = await installMcpPreset(presetId)
  if (result?.ok) ElMessage.success('MCP 预设已安装')
}

const removeMcpItem = async (serverName: string) => {
  try {
    await ElMessageBox.confirm(
      `将删除 MCP 服务“${serverName}”。重新注册前，它提供的工具和资源不会再出现。`,
      '删除 MCP 服务',
      {
        confirmButtonText: '删除服务',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  addPending(removingMcpNames, serverName)
  try {
    await removeMcp(serverName)
  } finally {
    removePending(removingMcpNames, serverName)
  }
}

const refreshMcpItem = async (serverName: string) => {
  addPending(refreshingMcpNames, serverName)
  try {
    await refreshMcp(serverName)
  } finally {
    removePending(refreshingMcpNames, serverName)
  }
}

const toggleMcpItem = async (serverName: string, enabled: boolean) => {
  addPending(togglingMcpNames, serverName)
  try {
    await toggleMcp(serverName, enabled)
  } finally {
    removePending(togglingMcpNames, serverName)
  }
}

const toggleAgentPluginItem = async (pluginId: string, enabled: boolean) => {
  addPending(togglingAgentPluginIds, pluginId)
  try {
    await toggleAgentPlugin(pluginId, enabled)
  } finally {
    removePending(togglingAgentPluginIds, pluginId)
  }
}

const disableConnectorItem = async (connectorId: string) => {
  const connector = connectorRows.value.find((item) => item.id === connectorId)
  if (!connector?.canDisable || connector.state === 'disabled') return
  addPending(disablingConnectorIds, connectorId)
  try {
    const result = await disableConnector(connectorId)
    if (result?.ok) {
      if (messageConnectorIds.includes(connectorId as MessageConnectorId)) {
        await loadConnectorConfig(connectorId as MessageConnectorId)
      }
      ElMessage.success('连接器已停用')
    } else if (result?.error) {
      ElMessage.error(result.error)
    }
  } finally {
    removePending(disablingConnectorIds, connectorId)
  }
}

const loadConnectorConfig = async (connectorId: MessageConnectorId) => {
  addPending(loadingConnectorConfigIds, connectorId)
  try {
    const result = await systemClient.connectorConfig(connectorId)
    connectorConfigs[connectorId] = result
    connectorDrafts[connectorId].enabled = result.enabled
    connectorDrafts[connectorId].botToken = ''
    connectorDrafts[connectorId].webhookSecret = ''
    connectorDrafts[connectorId].publicKey = ''
    connectorDrafts[connectorId].accountMode = result.accountMode || 'personal_bridge'
    connectorDrafts[connectorId].bridgeUrl = result.bridgeUrl || ''
    connectorDrafts[connectorId].bridgeProtocol = result.bridgeProtocol || 'generic'
    connectorDrafts[connectorId].bridgeToken = ''
    connectorDrafts[connectorId].clearBotToken = false
    connectorDrafts[connectorId].clearWebhookSecret = false
    connectorDrafts[connectorId].clearPublicKey = false
    connectorDrafts[connectorId].clearBridgeUrl = false
    connectorDrafts[connectorId].clearBridgeProtocol = false
    connectorDrafts[connectorId].clearBridgeToken = false
    if (connectorId === 'qq' || connectorId === 'wechat') await loadConnectorAccount(connectorId)
    return result
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : `${connectorId} 配置读取失败`)
    return null
  } finally {
    removePending(loadingConnectorConfigIds, connectorId)
  }
}

const clearConnectorSecret = (connectorId: MessageConnectorId, field: 'botToken' | 'webhookSecret' | 'publicKey' | 'bridgeUrl' | 'bridgeProtocol' | 'bridgeToken') => {
  const draft = connectorDrafts[connectorId]
  draft[field] = ''
  draft[`clear${field[0].toUpperCase()}${field.slice(1)}` as keyof ConnectorDraft] = true
}

const loadConnectorConfigs = async () => {
  await Promise.all(messageConnectorIds.map((connectorId) => loadConnectorConfig(connectorId)))
}

const saveConnectorConfig = async (connectorId: MessageConnectorId) => {
  const draft = connectorDrafts[connectorId]
  if (connectorId === 'discord' && draft.publicKey && !/^[0-9a-fA-F]{64}$/.test(draft.publicKey)) {
    ElMessage.warning('Discord Public Key 必须是 64 位十六进制字符串')
    return
  }
  const payload: MessageConnectorConfigUpdate = { enabled: draft.enabled }
  if (draft.clearBotToken) payload.clearBotToken = true
  else if (draft.botToken.trim()) payload.botToken = draft.botToken.trim()
  if (connectorId === 'telegram') {
    if (draft.clearWebhookSecret) payload.clearWebhookSecret = true
    else if (draft.webhookSecret.trim()) payload.webhookSecret = draft.webhookSecret.trim()
  }
  if (connectorId === 'discord') {
    if (draft.clearPublicKey) payload.clearPublicKey = true
    else if (draft.publicKey.trim()) payload.publicKey = draft.publicKey.trim()
  }
  if (connectorId === 'qq' || connectorId === 'wechat') {
    payload.accountMode = 'personal_bridge'
    if (draft.clearBridgeUrl) payload.clearBridgeUrl = true
    else if (draft.bridgeUrl.trim()) payload.bridgeUrl = draft.bridgeUrl.trim()
    if (draft.clearBridgeProtocol) payload.clearBridgeProtocol = true
    else if (draft.bridgeProtocol.trim()) payload.bridgeProtocol = draft.bridgeProtocol.trim()
    if (draft.clearBridgeToken) payload.clearBridgeToken = true
    else if (draft.bridgeToken.trim()) payload.bridgeToken = draft.bridgeToken.trim()
  }
  addPending(savingConnectorIds, connectorId)
  try {
    const result = await systemClient.updateConnectorConfig(connectorId, payload)
    connectorConfigs[connectorId] = result.config
    draft.enabled = result.config.enabled
    draft.botToken = ''
    draft.webhookSecret = ''
    draft.publicKey = ''
    draft.bridgeUrl = result.config.bridgeUrl || ''
    draft.bridgeProtocol = result.config.bridgeProtocol || 'generic'
    draft.bridgeToken = ''
    draft.clearBotToken = false
    draft.clearWebhookSecret = false
    draft.clearPublicKey = false
    draft.clearBridgeUrl = false
    draft.clearBridgeProtocol = false
    draft.clearBridgeToken = false
    await loadConnectors()
    const probe = await probeConnectorItem(connectorId, false)
    if (probe?.ok) ElMessage.success(`${connectorDisplayName(connectorId)} 设置已保存，${connectorProbeStatusLabel(probe)}`)
    else if (probe) ElMessage.warning(`${connectorDisplayName(connectorId)} 设置已保存，但${connectorProbeStatusLabel(probe)}`)
    else ElMessage.success(`${connectorDisplayName(connectorId)} 设置已保存，连接状态待检查`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '连接器设置保存失败')
  } finally {
    removePending(savingConnectorIds, connectorId)
  }
}

const accountStateLabel = (state: string) => ({ connected: '已连接', awaiting_scan: '等待登录', signed_out: '未登录', error: '桥接错误' }[state] || state)
const loginPersonalAccount = async (connectorId: 'qq' | 'wechat') => {
  addPending(accountBusyIds, connectorId)
  try { const account = await loginConnectorAccount(connectorId); if (account) ElMessage.success(account.loginUrl ? '登录请求已创建，请打开登录页' : `连接状态：${accountStateLabel(account.loginState)}`) } catch (error) { ElMessage.error(error instanceof Error ? error.message : '登录请求失败') } finally { removePending(accountBusyIds, connectorId); await loadConnectors().catch(() => undefined) }
}
const refreshPersonalAccount = async (connectorId: 'qq' | 'wechat') => {
  addPending(accountBusyIds, connectorId)
  try { await refreshConnectorAccount(connectorId) } finally { removePending(accountBusyIds, connectorId); await loadConnectors().catch(() => undefined) }
}
const logoutPersonalAccount = async (connectorId: 'qq' | 'wechat') => {
  addPending(accountBusyIds, connectorId)
  try { await logoutConnectorAccount(connectorId); ElMessage.success('账号已退出') } finally { removePending(accountBusyIds, connectorId); await loadConnectors().catch(() => undefined) }
}

const unbindPersonalAccount = async (connectorId: 'qq' | 'wechat') => {
  try {
    await ElMessageBox.confirm('将停用连接器并清除桥地址、协议令牌和账号状态。', '清除桥接配置', {
      type: 'warning',
      confirmButtonText: '清除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  addPending(accountBusyIds, connectorId)
  try {
    const result = await systemClient.unbindConnectorAccount(connectorId)
    connectorConfigs[connectorId] = result.config
    connectorAccounts.value[connectorId] = result.account
    const draft = connectorDrafts[connectorId]
    draft.enabled = result.config.enabled
    draft.bridgeUrl = result.config.bridgeUrl || ''
    draft.bridgeProtocol = result.config.bridgeProtocol || 'generic'
    draft.bridgeToken = ''
    draft.clearBridgeUrl = false
    draft.clearBridgeProtocol = false
    draft.clearBridgeToken = false
    await loadConnectors()
    ElMessage.success('桥接配置已清除')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '桥接配置清除失败')
  } finally {
    removePending(accountBusyIds, connectorId)
  }
}

const saveAgentPluginConfig = async (pluginId: string) => {
  const rawConfig = pluginConfigDrafts[pluginId]?.trim() || '{}'
  let config: unknown
  try {
    config = JSON.parse(rawConfig)
  } catch {
    ElMessage.error('插件配置必须是有效 JSON')
    return
  }

  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    ElMessage.error('插件配置必须是 JSON 对象')
    return
  }

  const result = await updateAgentPluginConfig(pluginId, config as Record<string, unknown>)
  if (result?.ok) {
    ElMessage.success('插件配置已保存')
  }
}

</script>

<style scoped>
.governance-console {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.connector-account-status {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.connector-bridge-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.connector-account-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.governance-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface);
  padding: 14px 16px;
  box-shadow: var(--yui-shadow-card);
}

.governance-toolbar > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.governance-toolbar strong {
  color: var(--yui-text);
  font-size: 16px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.governance-view-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--yui-border);
}

.governance-view-button {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 13px;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--yui-text);
  background: transparent;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease;
}

.governance-view-button:hover,
.governance-view-button:focus-visible {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-muted);
  outline: none;
}

.governance-view-button.active {
  border-color: color-mix(in srgb, var(--yui-accent) 34%, var(--yui-border));
  color: var(--yui-accent-strong, var(--yui-accent));
  background: var(--yui-accent-soft);
}

.governance-grid,
.host-grid {
  display: grid;
  gap: 14px;
}

.governance-grid {
  grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.65fr);
}

.lower-grid {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.7fr);
}

.governance-grid.single-view,
.lower-grid.single-view {
  grid-template-columns: minmax(0, 1fr);
}

.host-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 14px;
}

.panel-card,
.server-card,
.preset-card,
.host-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.host-card {
  display: flex;
  min-height: 112px;
  flex-direction: column;
  justify-content: space-between;
  padding: 16px;
  border-radius: var(--yui-radius-card);
}

.host-card span,
.host-card small {
  color: var(--yui-muted);
}

.host-card strong {
  color: var(--yui-text);
  font-size: 26px;
  letter-spacing: 0;
}

.host-card.green { background: var(--yui-success-soft); }
.host-card.blue { background: var(--yui-accent-soft); }
.host-card.violet { background: var(--yui-accent-soft); }

.panel-card {
  border-radius: var(--yui-radius-card);
}

.connector-card {
  overflow: hidden;
}

.connector-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.connector-item {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.connector-item p {
  margin: 0;
  color: var(--yui-muted);
  font-size: 13px;
  line-height: 1.5;
}

.connector-running {
  border-color: rgba(34, 197, 94, 0.28);
}

.connector-disabled,
.connector-uninstalled {
  opacity: 0.82;
}

.connector-failure {
  border-color: rgba(239, 68, 68, 0.28);
  background: var(--yui-danger-soft);
}

.connector-main,
.connector-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.connector-main > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.connector-main strong {
  color: var(--yui-text);
}

.connector-main span,
.connector-meta,
.connector-footer small {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.connector-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-wrap: anywhere;
}

.connector-footer {
  align-items: center;
}

.connector-config-tabs {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--yui-border);
}

.connector-config-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.connector-config-head,
.connector-config-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.connector-config-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.connector-config-head > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.connector-config-head strong {
  color: var(--yui-text);
}

.connector-config-head span {
  color: var(--yui-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.connector-config-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.connector-config-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.connector-probe-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  padding: 7px 9px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  color: var(--yui-muted);
  font-size: 12px;
}

.connector-probe-error {
  color: var(--yui-danger, #dc2626);
}

.connector-delivery-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--yui-border);
}

.connector-recovery-telemetry {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  padding: 8px 10px;
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
}

.connector-recovery-error {
  color: var(--yui-danger, #dc2626);
}

.connector-delivery-item {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--yui-radius-card);
  background: var(--yui-panel-surface, var(--yui-surface-raised));
}

.connector-delivery-item > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.connector-delivery-item strong,
.connector-delivery-item span,
.connector-delivery-item small {
  overflow-wrap: anywhere;
}

.connector-delivery-item strong {
  color: var(--yui-text);
  font-size: 12px;
}

.connector-delivery-item span,
.connector-delivery-item small {
  color: var(--yui-muted);
  font-size: 11px;
}

.connector-secret-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.connector-secret-row .el-input {
  min-width: 0;
  flex: 1;
}

.card-head,
.action-row,
.server-main,
.server-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head > div:first-child,
.server-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.card-head.compact {
  align-items: flex-start;
}

.side-stack,
.server-list,
.agent-plugin-list,
.permission-list,
.audit-timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-alert {
  margin-bottom: 12px;
  border-radius: 14px;
}

.mcp-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.mcp-filter-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  cursor: pointer;
  padding: 6px 10px;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.mcp-filter-button:hover,
.mcp-filter-button:focus-visible,
.mcp-filter-button.active {
  border-color: var(--yui-border-strong);
  background: var(--yui-surface-raised);
  outline: none;
}

.mcp-filter-button span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 700;
}

.mcp-filter-button strong {
  color: var(--yui-text);
  font-size: 12px;
}

.server-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border-radius: 18px;
}

.server-card.healthy { border-color: rgba(34, 197, 94, 0.28); }
.server-card.broken { border-color: rgba(239, 68, 68, 0.28); background: rgba(254, 242, 242, 0.76); }
.server-card.muted { opacity: 0.78; }

.server-status-dot {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: #ef4444;
  box-shadow: 0 0 0 6px rgba(239, 68, 68, 0.12);
}

.server-status-dot.online {
  background: #22c55e;
  box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.12);
}

.server-title {
  flex: 1;
}

.server-title strong,
.permission-item strong,
.audit-item strong {
  color: var(--yui-text);
}

.server-title span,
.server-meta,
.permission-item span,
.audit-item span,
.empty-inline {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.5;
}

.server-inventory,
.server-meta,
.history-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.server-meta {
  padding: 10px;
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.history-chip,
.permission-item,
.audit-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.history-chip span,
.history-chip small {
  color: var(--yui-muted);
  font-size: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 10px;
}

.preset-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-bottom: 12px;
}

.preset-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border-radius: var(--yui-radius-card);
}

.preset-card.installed {
  opacity: 0.72;
}

.preset-card > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.preset-card strong {
  color: var(--yui-text);
}

.preset-card span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.preset-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
}

.agent-plugin-list {
  margin-bottom: 14px;
}

.agent-plugin-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.agent-plugin-item.disabled {
  opacity: 0.76;
}

.agent-plugin-item.broken {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

.agent-plugin-main,
.plugin-config-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.agent-plugin-main > div:first-child {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.agent-plugin-main strong {
  color: var(--yui-text);
}

.agent-plugin-main span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.plugin-config-row :deep(.el-textarea) {
  min-width: 0;
}

.plugin-config-row {
  align-items: stretch;
}

.plugin-error {
  border-radius: var(--yui-radius-card);
}

.form-grid .wide {
  grid-column: 1 / -1;
}

.submit-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.permission-item {
  justify-content: space-between;
}

.permission-item > div,
.audit-item > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}

.permission-item.approved {
  border-color: rgba(34, 197, 94, 0.24);
  background: var(--yui-success-soft);
}

.permission-item.denied {
  border-color: rgba(239, 68, 68, 0.24);
  background: var(--yui-danger-soft);
}

.contribution-matrix {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, 1fr);
  overflow: hidden;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
}

.contribution-matrix > div {
  padding: 12px;
  border-bottom: 1px solid var(--yui-border);
  color: var(--yui-muted);
  font-size: 13px;
}

.contribution-matrix > div:nth-child(-n + 4) {
  background: rgba(15, 23, 42, 0.92);
  color: #e2e8f0;
  font-weight: 800;
}

.matrix-category {
  font-weight: 800;
  color: var(--yui-text) !important;
}

.audit-item {
  align-items: flex-start;
}

.audit-dot {
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 999px;
  background: #f59e0b;
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.12);
}

@media (max-width: 1200px) {
  .governance-grid,
  .lower-grid,
  .host-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .governance-toolbar {
    display: flex;
    flex-direction: column;
  }

  .toolbar-actions,
  .card-head,
  .server-main,
  .server-footer,
  .action-row {
    align-items: flex-start;
  }

  .card-head,
  .server-main,
  .server-footer,
  .action-row {
    flex-direction: column;
  }

  .contribution-matrix {
    grid-template-columns: 1fr;
  }

  .preset-card {
    grid-template-columns: 1fr;
  }

  .agent-plugin-main,
  .plugin-config-row {
    flex-direction: column;
  }

  .connector-list {
    grid-template-columns: 1fr;
  }

  .connector-main,
  .connector-footer {
    flex-direction: column;
  }

  .preset-meta {
    justify-content: flex-start;
  }
}
</style>
