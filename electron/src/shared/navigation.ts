export interface NavigationCapability {
  petControl?: boolean
  voice?: boolean
  memory?: boolean
  deployment?: boolean
  plugins?: boolean
  tasks?: boolean
  admin?: boolean
  companion?: boolean
  prompt?: boolean
}

export type NavigationSlot = 'primary' | 'secondary' | 'system' | 'admin'

export type NavigationAudience = 'core' | 'assistant' | 'admin'

export interface NavigationModuleRecord {
  id: string
  title: string
  desc: string
  order?: number
  enabled?: boolean
  capabilities?: NavigationCapability
  slot?: NavigationSlot
  audience?: NavigationAudience
  primary?: boolean
}

export const staticNavigationModuleRecords = [
  {
    id: 'overview',
    title: '运行状态',
    desc: '运行状态与异常',
    order: 0,
    enabled: true,
    capabilities: { petControl: true, companion: true, admin: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'companion',
    title: '桌宠总览',
    desc: '档案、关系与联动',
    order: 0,
    enabled: true,
    capabilities: { petControl: true, memory: true, voice: true, companion: true },
    slot: 'primary',
    audience: 'core',
    primary: false,
  },
  {
    id: 'chat',
    title: '对话中心',
    desc: '文本与语音对话',
    order: 1,
    enabled: true,
    capabilities: { voice: true, petControl: true, companion: true },
    slot: 'primary',
    audience: 'core',
    primary: true,
  },
  {
    id: 'prompt',
    title: '人格设定',
    desc: '提示词、角色卡与世界书',
    order: 2,
    enabled: true,
    capabilities: { companion: true, prompt: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'pet',
    title: '桌宠控制',
    desc: '模型、动作与位置',
    order: 3,
    enabled: true,
    capabilities: { petControl: true, companion: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'svc',
    title: '歌声转换',
    desc: 'SoulX 歌声转换',
    order: 4,
    enabled: true,
    capabilities: { voice: true, admin: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'tool',
    title: '本地能力',
    desc: '工具、MCP 与本地操作',
    order: 5,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'plugins',
    title: '插件管理',
    desc: '插件启停与配置',
    order: 6,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'infrastructure',
    title: '服务数据',
    desc: '服务、日志与备份',
    order: 7,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-governance',
    title: '权限审计',
    desc: '工具授权与审计',
    order: 8,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-trace',
    title: '任务追踪',
    desc: '任务、调度与追踪',
    order: 9,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'persona-memory',
    title: '行为记录',
    desc: '人格与心跳事件',
    order: 11,
    enabled: true,
    capabilities: { memory: true, petControl: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'settings',
    title: '系统设置',
    desc: '模型、语音与应用设置',
    order: 12,
    enabled: true,
    capabilities: { petControl: true, voice: true, companion: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'i18n',
    title: '语言管理',
    desc: '界面语言与文案',
    order: 13,
    enabled: true,
    capabilities: { admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'memory',
    title: '长期记忆',
    desc: '长期记忆与检索',
    order: 14,
    enabled: true,
    capabilities: { memory: true, companion: true },
    slot: 'secondary',
    audience: 'core',
    primary: true,
  },
  {
    id: 'deploy',
    title: '运行检查',
    desc: '接口、启动与打包',
    order: 15,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
] as const satisfies readonly NavigationModuleRecord[]

export type StaticNavigationModuleId = typeof staticNavigationModuleRecords[number]['id']
