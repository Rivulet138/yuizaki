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
    title: '运行总览',
    desc: '系统健康、桌宠联动与本地运行状态的高级总览',
    order: 0,
    enabled: true,
    capabilities: { petControl: true, companion: true, admin: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'companion',
    title: '桌宠首页',
    desc: '兼容旧链接并转到桌宠对话',
    order: 0,
    enabled: true,
    capabilities: { petControl: true, memory: true, voice: true, companion: true },
    slot: 'primary',
    audience: 'core',
    primary: false,
  },
  {
    id: 'chat',
    title: '桌宠对话',
    desc: '文本、语音、Agent 与桌宠联动的主对话区',
    order: 1,
    enabled: true,
    capabilities: { voice: true, petControl: true, companion: true },
    slot: 'primary',
    audience: 'core',
    primary: true,
  },
  {
    id: 'prompt',
    title: '人格提示词',
    desc: '桌宠场景提示词、人格、角色卡与世界书',
    order: 2,
    enabled: true,
    capabilities: { companion: true, prompt: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'pet',
    title: '桌宠模型',
    desc: 'Live2D / VRM 桌宠模型、穿透、动作、表情与位置控制',
    order: 3,
    enabled: true,
    capabilities: { petControl: true, companion: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'svc',
    title: '语音调试',
    desc: 'SVC 音色转换、试听与语音能力调试',
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
    desc: '查看工具、插件工具、MCP 能力与可授权的本地操作入口',
    order: 5,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'plugins',
    title: '桌宠技能',
    desc: '技能权限、执行、取消与审计',
    order: 6,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'infrastructure',
    title: '基础设施',
    desc: '系统日志、服务健康与数据备份',
    order: 7,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-governance',
    title: 'Agent 治理',
    desc: 'MCP 协议服务、技能权限与权限审批',
    order: 8,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-trace',
    title: '任务中心',
    desc: '任务调度、执行追踪与 Agent 运行流程',
    order: 9,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'persona-memory',
    title: '记忆调试',
    desc: '观察 persona、heartbeat、行为事件与记忆检索调试信息',
    order: 11,
    enabled: true,
    capabilities: { memory: true, petControl: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'settings',
    title: '模型与语音',
    desc: 'LLM、TTS、ASR、SVC 与桌宠 agent 运行配置',
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
    desc: '语言切换、翻译消息与错误文案查询',
    order: 13,
    enabled: true,
    capabilities: { admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'memory',
    title: '长期记忆',
    desc: '画像、关系、RAG 文档与可检索的长期记忆管理',
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
    desc: '后端接口、启动流程与打包检查',
    order: 15,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
] as const satisfies readonly NavigationModuleRecord[]

export type StaticNavigationModuleId = typeof staticNavigationModuleRecords[number]['id']
