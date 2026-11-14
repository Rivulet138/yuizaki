# Yuizaki 人格编辑器：技术取证与验收映射

> 2026-11-11 用户调整：已移除「设定检查」分区、来源预览、情境访谈及侧栏检查入口，并删除顶部角色信息栏。当前仅保留角色档案、世界书、行为规则。下文有关四分区、访谈和预览的验收是 2026-11-10 版本的历史记录，不代表当前界面；后续补充取证见 `persona-editor-additional-evidence-2026-11-11.md`。

- 取证日期、外部来源抓取日期：2026-11-10（Asia/Shanghai）。
- 状态：已实现并完成本地工程验收；未执行真实模型人格质量评测。
- 证据范围：Yuizaki 编辑器、提示词装配及 companion 更新链路，Character Card V2/SillyTavern、moeru-ai/airi、Open-LLM-VTuber，以及 Generative Agents、InCharacter、Character-LLM 三篇论文。
- 阅读约定：源码事实、设计建议和验证结果分别记录。源码描述以取证日期为界，优先按符号定位；验证结果以第 6 节执行记录为准。

## 1. 设计范围

- 角色、世界书、行为、设定检查四区导航；默认使用结构化角色表单，JSON 作为高级入口。description/personality 分开，mes_example 映射 exampleDialogue 并参与运行时装配。
- 导入 V1/V2/V3 核心字段、导出 V2 JSON；不是完整无损卡编辑器，不承诺扩展、资源包或图片元数据保真。firstMessage 仅作开场参考，不生成历史消息或事实。
- 明示工作区、work/daily 模式与 companion 档案作用域；保留现有保存、草稿、版本冲突和运行时应用机制。
- 本地预览不等于最终 LLM 上下文；四道访谈只供复制和人工检查，不自动调用付费模型或声称完成论文评测。角色设定与事实记忆保持独立。

## 2. 本地源码证据

本地链接均相对仓库中的本文件定位。以下说明实现职责与已识别的修复契约；验收结果见第 6 节。

### L1：界面导航、草稿与运行时应用

源码：[PromptPanel.vue](../electron/src/renderer/domains/prompt/views/PromptPanel.vue)。

- 角色、世界书、行为、设定检查通过分区导航呈现；WorkspacePromptEditor 接收 section，角色档案补充与工作区提示词保留独立入口。
- 工作区 system_prompt 与 companion persona_prompt 的草稿按各自 ID 记录 text/base。未修改的草稿可跟随远端文本；已修改的草稿在远端变化时保留并显示冲突。
- saveWorkspaceSystemPrompt / saveCompanionPersonaPrompt 捕获提交文本，响应后只在草稿未继续修改时覆盖内容。
- companion 保存与运行时应用分别记录；applySavedCompanionPrompt 在应用前后核对工作区、角色与已保存文本，应用失败可重试。
- 设定检查明确标为「本地设定预览」，说明不含当前轮次的召回记忆、工具和完整系统上下文。访谈按钮调用剪贴板写入，产品契约是不自动调用模型。

### L2：结构化表单、核心卡转换与世界书预览

源码：[WorkspacePromptEditor.vue](../electron/src/renderer/shared/components/prompt/WorkspacePromptEditor.vue)。

- 默认表单分别绑定名称、description、personality、scenario、instructions、exampleDialogue 和 firstMessage；JSON 位于折叠入口，并通过应用操作解析。
- parseCharacterCard / exportCharacterCard 调用点负责衔接核心字段转换；仅有调用点不能证明全部格式正确，须用 V1/V2/V3 夹具和 V2 输出验证。
- 角色、行为、世界书编辑调用 updateWorkspaceContext，分别提交 roleCard、promptEngineering、worldBook patch。
- resetRoleCardJson 从当前模型生成 JSON，并清除解析错误与 JSON 草稿标记；应覆盖读取当前卡、应用 JSON、表单编辑后同步等路径。
- 世界书预览以输入文本行数近似扫描深度，先按 insertionOrder 升序、再按 priority 降序及标题排序，预算主要累计内容字符并以乘 4 近似 token。排序字段已对齐服务端；扫描、预算和截断仍不是服务端装配器的精确复现。

### L3：角色参考块与完整运行时上下文

源码：[prompt_assembly.py](../python/modules/agent/prompt_assembly.py)，重点为 _role_card_prompt、_world_book_prompt、build_prompt_assembly。

- 角色块分别装配 description、personality、scenario、instructions、exampleDialogue、firstMessage；firstMessage 的契约为开场参考，不生成会话消息。
- _clean_text 对常规字段默认截到 1600 字符，名称 240、开场 500；示例入块不代表完整长文本已发送。_context_data_block 将内容标记为不可信数据并处理结构分隔符。
- compile_prompt_blocks 按 order、block_id 排序并渲染为 system 消息；角色内容仍是 untrusted/configuration，不能因此提升为核心策略。
- 世界书扫描真实 messages 的最后 scanDepth 条，以 insertionOrder、负 priority、标题排序；预算包含标题/分隔符，可跳过放不下的条目。排序字段与 L2 的预览一致；扫描单位、预算、截断及无关键词条目的处理仍存在差异。
- 最终装配还可能包含核心/模式/响应策略、动作约束、companion persona/style、workspace_prompt、会话摘要、检索记忆、关系策略、additional_blocks 以及 messages。本地预览不能代表最终 LLM 请求，也不能代表后续裁剪或传输后的内容。
- retrieved_chunks 通过独立检索证据块进入上下文；角色编辑与事实记忆写入继续分离。

### L4：持久化字段与并发保存

源码：[workspaceStore.ts](../electron/src/renderer/stores/workspaceStore.ts)，重点为 normalizeRoleCard、flushContextSave、queueContextSave、syncFromBackend、updateWorkspaceContext。

- description、exampleDialogue 已有默认值与字符串规范化；已用 store、真实组件行为、聊天请求和后端装配分别验证字段传递。
- 每工作区一个 running 保存者，按现有防抖周期合并排队；请求携带 contextRevision。409 后最多一次 rebase 重试，成功响应与尚未提交的 patch 合并。
- 后端同步区分远端版本、本地缓存版本及排队修改。新增表单继续复用 updateWorkspaceContext；不改变保存周期、版本协议、重试次数和草稿保留语义。

### L5：已保存 workspace context 作为默认 profile，显式请求覆盖

源码：[prompt_assembly.py](../python/modules/agent/prompt_assembly.py) 的 _resolve_prompt_profile / build_prompt_assembly；测试入口：[test_prompt_assembly.py](../python/tests/test_prompt_assembly.py)。

- 已实现：调用方未携带 request profile 时，已保存角色卡、世界书和行为设定仍参与装配；显式请求可以覆盖默认值，不必反向修改存储。
- 当前源码先按 workspace_id 取得当前工作区，再用该工作区 context 中的 promptMode、roleCard、worldBook、promptEngineering 解析 profile。promptMode 映射为 profile.mode；忽略其他 context 字段，避免把任意 UI 配置当作提示词。
- request profile 未提供的 section 使用已存值；显式提供字典 section 时，按 section 内一层字段合并，请求字段优先，不作任意深度合并。列表整体替换，不逐项合并。
- false、null、空字符串和空列表均是显式值，不能用真值回退吞掉；整个 section 为 null/false 时不恢复其已存字段。空字典 section 仍保留已存字段。覆盖后的值仍受装配器规范化及模式回退规则约束。
- 显式 request.mode 优先于已存 promptMode；work/daily 按指定模式，auto 等值按默认工作区 daily、其他工作区 work 回落。此处的 companion 是档案作用域，不能代替 daily 模式枚举。
- 解析不应修改请求对象或持久化 context，不借用其他工作区 profile。已有测试入口覆盖缺省 profile、请求字段覆盖、禁用、整段替换、工作区隔离及 auto 回退；本地目标测试通过，见第 6 节。

### L6：companion persona_prompt 的 null 清除契约

源码：[companion_api.py](../python/routes/companion_api.py) 的 CompanionPayload 与 PATCH 更新处理；前端入口：[PromptPanel.vue](../electron/src/renderer/domains/prompt/views/PromptPanel.vue) 的 saveCompanionPersonaPrompt；测试入口：[test_companion_persona_api.py](../python/tests/test_companion_persona_api.py)。

- 已实现：前端清空 persona 后发送 persona_prompt: null，后端必须清除已保存文本，不能因过滤 null 而保留旧人格。
- PATCH 通过 model_dump(exclude_unset=True) 区分字段缺失与显式 null；更新过滤只对 persona_prompt 放行 null，其他字段维持既有的 null 忽略语义。
- 字段缺失：保持原 persona；显式 null：将 persona_prompt 设为 null；空字符串：按字符串保存；非空字符串：替换原文本。前端将空白草稿规范化为 null，所以 API 空字符串用例与前端清空操作需分别检查。
- 清除后应从响应、持久化读取和重新装配三处核对：旧 persona 不再出现，companion_persona 块不生成。清除 persona 不表示移除 companion_style、角色卡或工作区偏好。
- 测试入口包含省略保留、null 清除、空串/文本替换、其他字段 null 不清除及清除后的装配；本地目标测试通过，见第 6 节。不能仅凭路由转发认定数据库清除和运行时应用已成功。

## 3. 六组一手外部证据

以下 URL 均于 2026-11-10 抓取或复核。GitHub 的 main/release 是可变引用，未固定 commit；结论限定于当次读取的指定函数。论文页和 PDF 作为元数据与方法依据，未宣称复现实验。

### E1：Character Card V2 与 SillyTavern 实际载入

- URL：[V2 规范](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md)；[原始文本](https://raw.githubusercontent.com/malfoyslastname/character-card-spec-v2/main/spec_v2.md)；[SillyTavern 解析器](https://github.com/SillyTavern/SillyTavern/blob/release/src/character-card-parser.js)。
- 位置：spec_v2.md 的 TavernCardV1/V2 类型、creator_notes、system_prompt、extensions；解析器 read/write。
- 事实：V1 六个核心文本字段分别存在；V2 使用 chara_card_v2、2.0、data 外壳，增加作者说明、系统/历史后指令、替代开场及扩展。作者说明不入提示词；扩展和已有可选数据有保留要求。SillyTavern read 优先读取 ccv3 块。
- 本地建议：拆开 description/personality，支持 mes_example，导出明确 V2 外壳；首消息参考与作者说明分清。
- 边界：只转换核心字段不能宣称完整 V2 编辑器合规或无损。丢弃未知扩展会偏离规范的保留要求，应在导入/导出附近披露兼容范围；兼容范围不含 V3 资源、PNG 嵌入或完整世界书语义。

### E2：moeru-ai/airi 的提示词装配

- URL：[airi-card.ts](https://github.com/moeru-ai/airi/blob/main/packages/stage-ui/src/stores/modules/airi-card.ts)；[原始文本](https://raw.githubusercontent.com/moeru-ai/airi/main/packages/stage-ui/src/stores/modules/airi-card.ts)。
- 位置：resolveSystemPrompt()。
- 事实：指定函数分别拼接 systemPrompt、description、personality、scenario、绘图组件指令及 Live2D 控制提示；注释说明位置敏感的 CCv3 字段暂不由此处装配。
- 本地建议：区分已存字段和真正进入 runtime 的字段；设定预览说明其来源及局限。
- 边界：不能推广为 AIRI 所有消息链路都不处理对话示例；也不能因为类型中存在某字段就宣称运行时已支持。Yuizaki 的结构化表单是本地产品选择，不是该函数证明的 UX 优势。

### E3：Open-LLM-VTuber 的 persona 配置与运行组合

- URL：[CharacterConfig](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/src/open_llm_vtuber/config_manager/character.py)；[ServiceContext](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/main/src/open_llm_vtuber/service_context.py)。
- 位置：CharacterConfig；construct_system_prompt()；handle_config_switch()。
- 事实：persona_prompt 与角色 ID、外观、agent、ASR/TTS 等配置分别定义；运行时在 persona 文本后追加部分工具/表情提示；替代角色配置与基础角色配置合并后加载。
- 本地建议：明确 companion 档案与工作区偏好的保存位置，并保留「已保存／已应用」不同状态。
- 边界：非空校验和配置切换不证明人格质量、隔离或一致性；无需搬入其完整 YAML 或语音配置结构。

### E4：Generative Agents（2023）

- URL：[元数据](https://arxiv.org/abs/2304.03442)；[v2 原文](https://arxiv.org/html/2304.03442v2)。
- 元数据：Joon Sung Park、Joseph C. O’Brien、Carrie J. Cai、Meredith Ringel Morris、Percy Liang、Michael S. Bernstein；Generative Agents: Interactive Simulacra of Human Behavior；arXiv:2304.03442，v1 2023-04-07，v2 2023-08-06；UIST 2023。
- 位置：§4.1 Memory and Retrieval、§4.2 Reflection、§4.3 Planning and Reacting、§6.5.2。
- 事实：系统将观察记忆、反思、计划与动态检索组合；原文记录了检索遗漏与记忆添饰问题。
- 本地建议：保持静态角色设定与事实记忆分开；提示用户角色背景不是已经发生的共同经历。
- 边界：25 个代理的沙盒架构不能由新增表单复现。编辑器不实现反思或记忆写入，也不据此保证长期一致性。

### E5：InCharacter（正式出版 2024）

- URL：[正式出版页](https://aclanthology.org/2024.acl-long.102/)；[原文 PDF](https://aclanthology.org/2024.acl-long.102.pdf)。
- 元数据：Xintao Wang、Yunze Xiao、Jen-tse Huang 等；InCharacter: Evaluating Personality Fidelity in Role-Playing Agents through Psychological Interviews；ACL 2024 Long Papers，1840–1873；DOI 10.18653/v1/2024.acl-long.102。
- 位置：访谈与人格评估方法、实验及 Limitations。
- 事实：通过开放式访谈与心理量表评估角色人格，实验涉及 32 个角色和 14 种量表；评估模型偏差与静态标签的限制需要考虑。
- 本地建议：提供固定情境问题及人工观察维度，比较修改前后的实际回答。
- 边界：本地问题由本项目编写，不是论文量表或评测协议；复制问题不代表执行评测。不自动调用模型、不自动评分、不引用论文实验准确率作为产品能力。

### E6：Character-LLM（2023）

- URL：[正式出版页](https://aclanthology.org/2023.emnlp-main.814/)；[原文 PDF](https://aclanthology.org/2023.emnlp-main.814.pdf)。
- 元数据：Yunfan Shao、Linyang Li、Junqi Dai、Xipeng Qiu；Character-LLM: A Trainable Agent for Role-Playing；EMNLP 2023，13153–13187；Anthology ID 2023.emnlp-main.814。
- 位置：经历重建、角色训练、§4.3–4.4、Limitations。
- 事实：用角色经历构建训练材料并微调；评估关注角色知识、价值观、性格、幻觉与稳定性，包括多轮追问。
- 本地建议：字段引导用户描述经历、动机、价值取舍与表达示例；设定检查观察未知知识和追问时的行为。
- 边界：提示词示例不等于模型微调；不能继承论文效果，不保证模型不会幻觉。选用此篇满足第三篇论文范围，第三篇论文采用 Character-LLM，未纳入 RoleLLM。

## 4. 问题—改进—验证映射

以下为本地工程验收映射，实际执行范围和结果登记在第 6 节；不代表真实模型的人格质量评测。

| ID | 问题与证据 | 约定改进 | 最小有意义验证 | 结果/证据 |
| --- | --- | --- | --- | --- |
| V01 | JSON 默认入口难以区分字段用途；L2、E1 | 结构化角色表单为默认，JSON 高级入口可折叠 | 用不同值编辑名称、背景、性格、场景、规则、示例和开场；切换页面后确认值及标签；窄屏可访问 | 工程验证通过，见第 6 节 |
| V02 | 各区混排，工作区与 companion 易混；L1–L3、E3 | 角色/世界书/行为/设定检查导航，提示当前工作区与档案 | 切换四区及工作区，确认内容、选中态、draft、scope 文案；不会把档案文字写到错误工作区 | 工程验证通过，见第 6 节 |
| V03 | description/personality 混存会丢失字段语义；L2、E1 | 两字段独立导入、持久化、装配 | 构造同时含两字段且文本不同的卡，保存/重载后逐字段断言，后端块分别出现且不重复折入 instructions | 工程验证通过，见第 6 节 |
| V04 | mes_example 可能被静默漏掉；L2–L4、E1–E2 | 映射到 exampleDialogue 并进入 runtime 角色参考块 | V1/V2/V3 各一份夹具；重载后示例仍在；后端测试含示例、禁用卡时不出现；验证长度上限和分隔符转义 | 工程验证通过，见第 6 节 |
| V05 | 核心转换与完整卡兼容易混；E1 | 导入核心 V1/V2/V3；导出 V2；披露不支持/损失项 | 检查 spec/spec_version/data、全部 V2 必填字段及类型；测试非法 JSON、非对象、未知版本；检查导出核心值与世界书转换 | 工程验证通过，见第 6 节 |
| V06 | 首消息易被当作真实会话；L3、E1 | firstMessage 明确仅作开场风格参考 | 导入首消息后不新增/发送 assistant 消息，不创建历史事实；预览与后端参考文案一致；真实聊天另行触发 | 工程验证通过，见第 6 节 |
| V07 | work/daily 与 companion 档案层次不同；L1、L3 | UI 明示模式与持久化 scope，不暗改 mode 枚举 | 覆盖 default/其他工作区、auto/work/daily；切换模式不清空角色卡；保存 workspace/companion 分别验证请求与应用状态 | 工程验证通过，见第 6 节 |
| V08 | 新表单可能破坏已有草稿与并发保护；L1、L4 | 复用 save/concurrency，保持版本和队列协议 | 保存飞行中继续输入、切换目标、晚到响应、409 一次重试/冲突、失败重试、runtime 应用失败；新输入和草稿保持 | 工程验证通过，见第 6 节 |
| V09 | 预览与真实装配有不同动态输入和预算；L2–L3、E2–E3 | 名为「本地设定预览」，标明未含动态上下文 | 预览显示来源与不包含项；不称最终请求；世界书预览按插入顺序及优先级排序，保留近似预览标识；不宣称精确 token 预算 | 工程验证通过，见第 6 节 |
| V10 | 访谈按钮可能被误解为自动评测；E5–E6 | 固定问题只复制；人工检查，无自动付费调用 | 点击复制验证剪贴板；拦截网络确认不发 LLM 请求；无分数、通过徽章或「已完成论文评测」文案 | 工程验证通过，见第 6 节 |
| V11 | 人设或世界书虚构可能污染事实记忆；L3、E4 | 记忆独立，编辑与检查不写事实记忆 | 使用内存替身/请求拦截验证编辑、导入、预览、复制不会调用事实记忆写入；原检索链路保持独立 | 工程验证通过，见第 6 节 |
| V12 | JSON 草稿与表单同步可能覆盖未应用内容；L2 | 显式应用、读取当前卡与表单同步保持清晰 | 覆盖非法 JSON、未应用草稿、读取当前卡、应用后规范化及切换工作区；检查无递归、无草稿意外覆盖 | 工程验证通过，见第 6 节 |
| V13 | 缺少请求 profile 时可能遗漏已保存设置；L5 | saved workspace context 默认值，显式 request profile 优先 | 缺省/部分覆盖、false/null/空串/空列表、整段替换、一层合并、auto 回退、工作区隔离、输入对象不变；核对真实装配 | 工程验证通过，见第 6 节 |
| V14 | null 过滤可能导致清空后旧人格仍生效；L6 | persona_prompt 单字段 null 清除契约 | PATCH 省略/null/空串/替换；响应与持久化一致；其他 null 字段保持原语义；后续装配无旧 persona，前端保存/应用状态准确 | 工程验证通过，见第 6 节 |

### 核心字段转换契约

| 本地字段/用途 | V1 源字段 | V2/V3 核心源字段 | V2 导出目标 | 约定边界 |
| --- | --- | --- | --- | --- |
| name | name | data.name | data.name | 空值仍满足类型 |
| description | description | data.description | data.description | 不再替代 personality |
| personality | personality | data.personality | data.personality | 不拼入背景 |
| scenario | scenario | data.scenario | data.scenario | 设定参考，不等于实际发生 |
| firstMessage | first_mes | data.first_mes | data.first_mes | 仅风格参考 |
| exampleDialogue | mes_example | data.mes_example | data.mes_example | 参考文本，不自动伪造成历史消息 |
| instructions | 本地 instructions 别名（如保留） | system_prompt/本地别名等需定义 | 建议 data.system_prompt | 本地运行仍受核心策略限制；不是任意系统覆盖 |
| 历史后指令 | 无标准核心字段 | data.post_history_instructions | 无独立本地字段时不承诺往返 | 不得把折入 instructions 宣称实现了历史后插入语义 |
| 世界书 | character_book 别名（如保留） | data.character_book | data.character_book（可选） | 逐字段映射；不能直接假定本地 camelCase 对象等同 V2 类型 |

V2 输出另需提供 creator_notes、post_history_instructions、alternate_greetings、tags、creator、character_version、extensions 等必填字段的合规默认值（字符串、数组、对象）。默认空值不代表原始元数据已保留。creator_notes 不进入 runtime；未知扩展/额外资源可能不保留时，应明确告知转换范围，不能使用「完整兼容」「无损往返」描述。

## 5. 当前界面的四道固定访谈题

题目与 [PromptPanel.vue](../electron/src/renderer/domains/prompt/views/PromptPanel.vue) 的 interviewCases 同步，按界面顺序列出中英文原文。这是项目自拟的人工设定检查，不是 InCharacter 原题、量表或心理诊断。复制操作不自动调用模型，也不写入事实记忆。

| ID / 标题 | 中文问题 | 英文问题 | 人工观察点 |
| --- | --- | --- | --- |
| identity / 身份与经历（Identity） | 你是谁？挑一段对你很重要的经历，说说它为什么改变了你。 | Who are you? Describe an important experience and how it changed you. | 身份与经历是否贴合设定；区分角色背景与真实共同经历 |
| values / 分歧与价值观（Values） | 如果我的看法和你不同，你会怎么回应？请给一个具体例子。 | If we disagreed, how would you respond? Give a concrete example. | 价值取舍、分歧表达和对用户的尊重 |
| support / 陪伴与表达（Support） | 今天的计划全乱了，我有点沮丧。你会怎么陪我重新开始？ | My plans fell apart and I feel discouraged. How would you help me start again? | 陪伴语气、支持方式与具体回应习惯 |
| memory / 记忆与边界（Memory boundaries） | 说一件我们一起经历过的事。如果没有可靠记录，请直接告诉我你不确定。 | Tell me about something we experienced together. If you have no reliable record, say you are unsure. | 无可靠记录时表达不确定，不虚构共同经历 |

人工检查记录设定版本、模型/采样配置、实际回答及偏离；未发送时不填写评测结论。单次回答不能保证整体人格一致性。

## 6. 本地工程验收（2026-11-10）

机器可读记录：[`persona-editor-validation-2026-11-10.json`](persona-editor-validation-2026-11-10.json)。

| 检查 | 实际范围 | 结果 |
| --- | --- | --- |
| 前端定向回归 | `vitest run`：角色卡转换、PromptPanel 草稿/保存、WorkspacePromptEditor、workspace/chat stores、ChatPanel async/drafts、SettingsPanel、navigation，共 9 个文件 | **186 passed** |
| 后端定向回归 | `python/.venv/Scripts/python.exe -m pytest`：prompt assembly、companion persona API、workspace context API/repository/store/migration，共 6 个文件 | **82 passed** |
| 前端静态检查 | 本轮 11 个 TS/Vue 文件 ESLint；renderer changed type gate | ESLint 通过，类型错误 **0** |
| 构建与体积 | `vite build --logLevel warn`、`node scripts/audit-renderer-bundle.mjs`（工作目录 `electron`） | 通过；保留原有 Cubism classic-script 打包提示 |
| Python 静态检查 | companion API 与两个测试文件 Ruff；装配器 Ruff 除既有两项基线外通过；compileall | 新增代码检查通过；既有 `BLE001:32`、`SIM103:271` 未改动 |
| 浏览器交互 | Chrome/Playwright：结构化字段→context、四区切换、JSON 显式应用/无效值保护、复制问题、键盘导航、保存请求 | **7 组检查通过，pageerror 0** |
| 显示检查 | 1600×1050、1000×950、800×950；浅色及深色；检查文档/表单无水平溢出并人工查看截图 | 通过 |
| HTTP 写入边界 | 浏览器测试用隔离 context 拦截非 GET API；确认角色字段的保存请求，断言编辑/检查未产生 memory 或生成接口写入 | 通过；未调用付费模型 |
| 人工模型访谈 | 四个固定问题可复制，真实模型回答尚未收集 | **未执行**；无人格评分、无论文效果复现声明 |

浏览器使用测试数据和拦截的写请求，不覆盖用户的已保存角色内容。截图位于本机 Codex visualizations 的 `01a1c0d5-02c6-70a2-919f-65be971a0e2f` 目录：`persona-editor-desktop.jpg`、`persona-review-desktop.jpg`、`persona-editor-1000.jpg`、`persona-editor-800.jpg`、`persona-editor-dark.jpg`。

独立复查发现并修复：V2 导出卡将 `system_prompt` 编辑为空字符串后，旧 `extensions.yuizaki.instructions` 被错误恢复。解析现按字段是否存在决定 fallback，新增 7 项回归覆盖显式清空及 extension-only fallback。

本次验收证明字段流转、保存/清空、配置装配及界面交互；长期一致性、不同模型下的角色表现仍需真实对话评测。引用论文提供设计与检查方法，不构成效果保证。
