from __future__ import annotations

from dataclasses import dataclass


def _skill(
    skill_id: str,
    name: str,
    description: str,
    stage: str,
    tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": skill_id,
        "name": name,
        "description": description,
        "kind": "skill",
        "audience": "core",
        "stage": stage,
        "tags": tags or [],
    }


@dataclass
class OrchestrationRegistry:
    def snapshot(self) -> dict[str, object]:
        agents = [
            {
                "id": "yuizaki.companion-orchestrator",
                "name": "Companion Orchestrator",
                "description": "协调记忆召回、能力路由和关系更新的核心 Agent。",
                "role": "orchestrator",
                "audience": "core",
            },
            {
                "id": "yuizaki.task-router",
                "name": "Task Router",
                "description": "把即时任务和计划任务送入规划与执行链路。",
                "role": "router",
                "audience": "core",
            },
            {
                "id": "yuizaki.memory-reflector",
                "name": "Memory Reflector",
                "description": "把执行结果整理成关系与记忆更新，供后续召回。",
                "role": "reflector",
                "audience": "admin",
            },
        ]

        skills = [
            _skill(
                "yuizaki.observe-recall-loop",
                "Observe / Recall Loop",
                "收集运行时输入，召回相关记忆，并送入桌宠 Agent 链路。",
                "observe-recall",
                ["memory", "companion"],
            ),
            _skill(
                "yuizaki.capability-routing",
                "Capability Routing",
                "通过统一能力快照选择内置工具、插件工具或 MCP 工具。",
                "decide-act",
                ["router", "capability"],
            ),
            _skill(
                "yuizaki.skill.voice-dialogue-chain",
                "Voice Dialogue Chain",
                "把麦克风输入整理成文本，交给 LLM 生成回复，再触发 TTS 和桌宠动作。",
                "voice-dialogue",
                ["asr", "llm", "tts", "pet"],
            ),
            _skill(
                "yuizaki.skill.long-dialogue-summary",
                "Long Dialogue Summary",
                "把长聊天、语音转写和会话记录整理成摘要、决定、待办和风险。",
                "memory-summary",
                ["summary", "memory", "task"],
            ),
            _skill(
                "yuizaki.skill.companion-reflection",
                "Companion Reflection",
                "分析对话里的情绪、沟通模式和可改进点，用于长期桌宠记忆和关系反馈。",
                "memory-reflection",
                ["reflection", "memory"],
            ),
            _skill(
                "yuizaki.skill.memory-capture",
                "Memory Capture",
                "把事实、偏好、项目决定和待办沉淀到可检索记忆。",
                "memory-capture",
                ["memory", "recall"],
            ),
            _skill(
                "yuizaki.skill.realtime-screen-vision",
                "Realtime Screen Vision",
                "把桌面截图作为短时视觉帧交给桌宠理解窗口、布局和用户动作；OCR 只在需要精确读字时作为备用能力。",
                "perception-vision",
                ["vision", "screen", "desktop-pet"],
            ),
            _skill(
                "yuizaki.skill.local-file-organizer",
                "Local File Organizer",
                "识别本机文件、素材和导入资源用途，给出整理、重命名和归档建议。",
                "local-automation",
                ["filesystem", "local"],
            ),
            _skill(
                "yuizaki.skill.ocr-document-organizer",
                "OCR Document Organizer",
                "读取截图、票据或扫描文档里的关键信息，生成结构化条目并建议归档位置。",
                "document-ocr",
                ["ocr", "document"],
            ),
            _skill(
                "yuizaki.skill.webapp-testing",
                "Webapp Testing",
                "用 Playwright 检查本地 Electron/Vite 页面、交互、截图和控制台错误。",
                "quality-frontend",
                ["playwright", "qa"],
            ),
            _skill(
                "yuizaki.skill.frontend-design",
                "Frontend Design Polish",
                "优化桌宠面板、设置页、本地能力页和调试页的布局、文案、状态和响应式细节。",
                "frontend-design",
                ["ui", "ux"],
            ),
            _skill(
                "yuizaki.skill.interface-hardening",
                "Interface Hardening",
                "检查空状态、错误提示、长文本溢出、中文文案、深色模式和失败降级。",
                "frontend-hardening",
                ["i18n", "error", "layout"],
            ),
            _skill(
                "yuizaki.skill.code-review",
                "Code Review",
                "按缺陷、回归风险、缺失测试和行为变化审查改动。",
                "quality-code",
                ["review", "quality"],
            ),
            _skill(
                "yuizaki.skill.repo-analysis",
                "Repository Analysis",
                "只读梳理代码结构、调用关系和风险点，用于复杂改动前建立事实图。",
                "repo-analysis",
                ["analysis"],
            ),
            _skill(
                "yuizaki.skill.best-practice-research",
                "Best Practice Research",
                "优先查官方文档和上游资料，适合接新模型、TTS、ASR、MCP、Ollama、LM Studio 或 SDK 前使用。",
                "research",
                ["docs", "research"],
            ),
            _skill(
                "yuizaki.skill.mcp-builder",
                "MCP Service Builder",
                "把本地工具、资源读取、浏览器控制或外部服务包装成标准 MCP 工具。",
                "mcp",
                ["mcp", "tool"],
            ),
            _skill(
                "yuizaki.skill.skill-authoring",
                "Skill Authoring",
                "把常用链路沉淀成可复用 Skill，包括触发条件、输入、流程、校验和失败兜底。",
                "skill-authoring",
                ["skill", "workflow"],
            ),
            _skill(
                "yuizaki.skill.image-generation",
                "Image Generation",
                "生成或编辑头像、背景、UI 参考图和透明素材。",
                "media-image",
                ["image"],
            ),
            _skill(
                "yuizaki.skill.image-enhancement",
                "Image Enhancement",
                "提升截图清晰度和可读性，适合 UI 验收、反馈图和文档插图。",
                "media-image",
                ["image", "screenshot"],
            ),
            _skill(
                "yuizaki.skill.document-export",
                "Document Export",
                "把摘要、报告和会话结果导出为 PDF、DOCX、PPTX 或 XLSX。",
                "document-export",
                ["pdf", "docx", "pptx", "xlsx"],
            ),
            _skill(
                "yuizaki.skill.spreadsheet-helper",
                "Spreadsheet Helper",
                "编写和调试 Excel/表格公式，适合导入数据、统计结果和批量整理。",
                "document-spreadsheet",
                ["spreadsheet"],
            ),
            _skill(
                "yuizaki.skill.task-triage",
                "Task Triage",
                "把用户反馈、长对话或问题清单拆成优先级、复现步骤、下一步动作和回复草稿。",
                "task-triage",
                ["triage", "task"],
            ),
            _skill(
                "yuizaki.skill.agent-trace-debug",
                "Agent Trace Debug",
                "分析 LLM、工具调用、记忆召回和插件钩子的执行轨迹，用于排查输出和耗时问题。",
                "agent-debug",
                ["trace", "agent"],
            ),
            _skill(
                "yuizaki.skill.release-notes",
                "Release Notes",
                "把技术改动整理成用户可读的更新说明。",
                "release",
                ["release"],
            ),
            _skill(
                "yuizaki.skill.design-system",
                "Design System",
                "沉淀颜色、间距、组件状态和文案规则，让设置页、桌宠页和能力页保持一致。",
                "frontend-design",
                ["design-system"],
            ),
            _skill(
                "yuizaki.skill.web-research",
                "Web Research",
                "对需要时效性的模型、插件、依赖和工具信息进行搜索、比对和资料整理。",
                "research",
                ["web", "research"],
            ),
            _skill(
                "yuizaki.skill.content-writing",
                "Content Writing",
                "把调研结果、教程、FAQ 和版本说明写成清晰中文内容。",
                "authoring",
                ["writing"],
            ),
            _skill(
                "yuizaki.skill.project-planning",
                "Project Planning",
                "把模糊需求拆成范围、里程碑、验收标准和风险。",
                "planning",
                ["plan"],
            ),
            _skill(
                "yuizaki.skill.quality-cleanup",
                "Quality Cleanup",
                "清理重复抽象、冗余 UI 文案、过度包装和不一致命名，保持改动小而可验收。",
                "quality-cleanup",
                ["cleanup"],
            ),
        ]

        commands = [
            {
                "id": "yuizaki.create-once-task",
                "name": "Create Once Task",
                "description": "在本地调度器中创建只执行一次的任务。",
                "kind": "command",
                "audience": "core",
                "target": "/api/system/schedules/once",
            },
            {
                "id": "yuizaki.create-interval-task",
                "name": "Create Interval Task",
                "description": "在本地调度器中创建按间隔重复执行的任务。",
                "kind": "command",
                "audience": "core",
                "target": "/api/system/schedules/interval",
            },
        ]

        hooks = [
            {
                "id": "yuizaki.before-pipeline",
                "name": "before_pipeline",
                "description": "链路执行前调整上下文的插件钩子。",
                "kind": "hook",
                "audience": "admin",
                "stage": "observe",
            },
            {
                "id": "yuizaki.before-llm",
                "name": "before_llm",
                "description": "模型调用前调整提示词和上下文的插件钩子。",
                "kind": "hook",
                "audience": "admin",
                "stage": "decide",
            },
            {
                "id": "yuizaki.after-tool",
                "name": "after_tool",
                "description": "工具调用后处理适配与关系更新副作用的插件钩子。",
                "kind": "hook",
                "audience": "admin",
                "stage": "reflect",
            },
        ]

        return {
            "agents": agents,
            "skills": skills,
            "commands": commands,
            "hooks": hooks,
            "summary": {
                "agents": len(agents),
                "skills": len(skills),
                "commands": len(commands),
                "hooks": len(hooks),
            },
        }
