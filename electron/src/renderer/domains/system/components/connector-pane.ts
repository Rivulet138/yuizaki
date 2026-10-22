import type {
  ConnectorAccountSnapshot,
  ConnectorDeliveryItem,
  ConnectorProbeSnapshot,
  ConnectorRecoverySnapshot,
  MessageConnectorConfigSnapshot,
  MessageConnectorConfigUpdate,
  QqBridgeSnapshot,
} from '@/../shared/agent'

/** Connector tabs rendered by the governance panel, in display order. */
export const messageConnectorIds = ['telegram', 'discord', 'qq', 'wechat'] as const

export type MessageConnectorId = (typeof messageConnectorIds)[number]

/**
 * Editable mirror of one connector config: the snapshot fields the operator can
 * change, plus write-only secret drafts that are never hydrated from the backend.
 */
export type ConnectorDraft = MessageConnectorConfigUpdate & {
  botToken: string
  webhookSecret: string
  publicKey: string
  accountMode: string
  bridgeUrl: string
  bridgeProtocol: string
  bridgeToken: string
  clearBotToken: boolean
  clearWebhookSecret: boolean
  clearPublicKey: boolean
  clearBridgeUrl: boolean
  clearBridgeProtocol: boolean
  clearBridgeToken: boolean
}

export type ConnectorSecretField =
  | 'botToken'
  | 'webhookSecret'
  | 'publicKey'
  | 'bridgeUrl'
  | 'bridgeProtocol'
  | 'bridgeToken'

export type PaneTagType = 'success' | 'info' | 'warning' | 'danger'

/**
 * The complete contract between the governance panel and one connector pane.
 *
 * The pane is presentational: it renders one connector and calls back into the
 * panel for every mutation. Handing the whole contract over as a single typed
 * object keeps that boundary explicit and, unlike the previous markup, gives the
 * pane template a real typed scope for its connector id — `v-for` variables do
 * not survive into it (they were reported as `TS2304` by vue-tsc), a prop does.
 */
export interface ConnectorPaneApi {
  // ---- state -------------------------------------------------------------
  connectorConfigs: Partial<Record<MessageConnectorId, MessageConnectorConfigSnapshot>>
  connectorDrafts: Record<MessageConnectorId, ConnectorDraft>
  connectorAccounts: Record<string, ConnectorAccountSnapshot>
  qqBridge: QqBridgeSnapshot | null
  qqBridgeStateLabel: string
  qqBridgeTagType: PaneTagType
  bridgeBusy: boolean
  signServerDraft: string
  loadingConnectorConfigIds: ReadonlySet<string>
  savingConnectorIds: ReadonlySet<string>
  probingConnectorIds: ReadonlySet<string>
  accountBusyIds: ReadonlySet<string>
  retryingDeliveryKeys: ReadonlySet<string>
  cancellingEventIds: ReadonlySet<string>
  resolvingEventIds: ReadonlySet<string>
  connectorProbeRequest: { loading: boolean }
  connectorDeliveriesRequest: { loading: boolean }

  // ---- derived helpers ---------------------------------------------------
  connectorDisplayName: (connectorId: MessageConnectorId) => string
  connectorProbeSnapshot: (connectorId: MessageConnectorId) => ConnectorProbeSnapshot | null | undefined
  connectorProbeStatusLabel: (snapshot: ConnectorProbeSnapshot) => string
  connectorProbeTagType: (snapshot: ConnectorProbeSnapshot) => PaneTagType
  connectorRecoverySnapshot: (connectorId: MessageConnectorId) => ConnectorRecoverySnapshot | null | undefined
  formatRecoveryTime: (timestamp: number | null | undefined) => string
  connectorDeliveryRows: (connectorId: MessageConnectorId) => ConnectorDeliveryItem[]
  connectorDeliveryStatusLabel: (status: string) => string
  accountStateLabel: (state: string) => string

  // ---- actions -----------------------------------------------------------
  setSignServerDraft: (value: string) => void
  copyConnectorWebhookPath: (connectorId: MessageConnectorId) => Promise<void>
  loadConnectorConfig: (connectorId: MessageConnectorId) => Promise<void>
  probeConnectorItem: (connectorId: MessageConnectorId, notify?: boolean) => Promise<unknown>
  saveConnectorConfig: (connectorId: MessageConnectorId) => Promise<void>
  loadConnectorDeliveries: (connectorId: MessageConnectorId) => Promise<unknown>
  clearConnectorSecret: (connectorId: MessageConnectorId, field: ConnectorSecretField) => void
  installManagedBridge: () => Promise<void>
  startManagedBridge: () => Promise<void>
  refreshManagedBridge: () => Promise<void>
  stopManagedBridge: () => Promise<void>
  logoutManagedBridge: () => Promise<void>
  saveSignServer: () => Promise<void>
  loginPersonalAccount: (connectorId: MessageConnectorId) => Promise<void>
  refreshPersonalAccount: (connectorId: MessageConnectorId) => Promise<void>
  logoutPersonalAccount: (connectorId: MessageConnectorId) => Promise<void>
  unbindPersonalAccount: (connectorId: MessageConnectorId) => Promise<void>
  retryDeliveryItem: (connectorId: MessageConnectorId, deliveryKey: string) => Promise<void>
  cancelConnectorEventItem: (connectorId: MessageConnectorId, eventId: string) => Promise<void>
  resolveConnectorEventItem: (
    connectorId: MessageConnectorId,
    eventId: string,
    outcome: 'delivered' | 'failed',
  ) => Promise<void>
}
