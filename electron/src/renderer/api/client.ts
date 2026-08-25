import { petControl } from '@/utils/petControl'
import { systemClient } from './clients/system-client'
import { summaryClient } from './clients/summary-client'
import { settingsClient } from './clients/settings-client'
import { memoryClient } from './clients/memory-client'
import { chatClient, shortcutClient } from './clients/chat-client'
import { pluginClient } from './clients/plugin-client'
import { resourceClient } from './clients/resource-client'
import { workspaceClient } from './clients/workspace-client'
import { companionClient } from './clients/companion-client'
import { i18nClient } from './clients/i18n-client'
import { proactiveClient } from './clients/proactive-client'

export const petControlClient = petControl

export { systemClient, summaryClient, settingsClient, memoryClient, chatClient, shortcutClient, pluginClient, resourceClient, workspaceClient, companionClient, i18nClient, proactiveClient }
