# Stu Current Capabilities Audit

日期：2026-09-17  
范围：读取仓库现有产品、设计、技术、实施、运维与历史 QA 文档，并交叉检查当前 UI、API、领域逻辑、数据模型及测试。

本次为静态审计，没有启动服务、执行测试或验证线上运行。“已接通”表示可找到 UI → API → 数据持久化的实现路径，不表示本轮重新实测通过。历史 QA 结果和实施计划中的预期结果另行标注。

## 1. 结论

Stu 已有可复用的家庭菜谱应用基础：登录与家庭、菜谱管理、手动计划和餐次编辑、生成计划表单、通用待办、聊天 Agent、Web/Lark 接入和中英界面。

当前产品主线仍是“存菜谱、聊天、排菜名”。新需求所依赖的 **周计划 → 周末备餐 → 实存份数 → 每日执行 → 喜好和历史影响下周** 尚未形成闭环。尤其不能把“文档要求支持”或“已有数据表”当作完整实现。

## 2. 当前功能盘点

| 模块 | 当前代码中的能力 | 缺口或限制 | 新设计处理 |
| --- | --- | --- | --- |
| 登录、家庭、Lark 绑定 | 有登录、会话、家庭邀请、绑定及数据范围控制路径 | 新的家庭共享库存需沿用归属及权限；本轮未重新实测 | 复用 |
| 菜谱管理 | 菜谱增删改查、食材、步骤、餐型、适龄、图片地址、准备和烹饪分钟字段 | 无可管理的自定义 tag、份数基准、步骤级人工/等待时间 | 扩展 Recipes |
| 菜谱文本解析 | 有文本提取、结构化解析服务，Agent 可预览后保存 | 导入页主要是状态列表；不能据此认定所有导入方式已打通 | 保留基础，完善入口与解析 |
| 图片、链接、Excel 导入 | 有输入类型、适配器、原始输入及状态模型 | 图片/Excel 仅透传对象 key；解析时只发文本；URL 适配器固定抛出需要 worker；聊天附件不是可操作上传控件 | 图片和文本作为必须补全的能力；其他准确标记状态 |
| 手动周计划 | 计划与餐次 CRUD；按日期和餐型展示已有条目 | 普通 Plan 是纵向日期卡片；不是固定七天三餐周历；一条餐次只引用一个菜谱 | 共享日历与多组成 Meal Card |
| AI 计划生成 | 日期、餐型、人数、偏好、备注表单；生成并保存七天结果 | 每种餐型取三个推荐循环填入；生成后直接保存，没有草案/确认生命周期 | 重做整体规划及确认流程 |
| 推荐 | 有三结果协议、过滤与评分函数；家庭候选和生成候选来源 | 实际家庭候选用固定评分特征；未按真实库存、评分、近期历史计算；新生成候选只有菜名和 UUID | 接真实上下文及可验证约束 |
| 单餐替换 | 可以手动编辑餐次；服务和 Agent 有单项替换基础 | 老替换预览按日期找第一个条目，三餐场景范围不够精确；无餐卡上下文聊天与批量范围规则 | 以稳定餐卡/组成标识定位 |
| 备餐 / Todo | grocery 和 todo 的增删改、日期、完成勾选、家庭可见性 | 通用待办没有备餐产出、餐次依赖、分类排程、人工与等待计算 | 新增专门 Prep 流程 |
| 采购清单 | 有聚合器、shopping 表和只读查询；另有可编辑 grocery todo | 聚合器未接入生产计划创建；计划不装配食材；grocery todo 与 shopping 不是同一套闭环 | 作为 Plan / Prep 辅助能力接通 |
| 每餐完成 / 没做 | 餐次可以编辑或删除 | 未见独立执行状态、实际份数和历史消费记录 | 新增，和库存联动 |
| 反馈与喜好 | 有文本反馈 API、反馈事件、菜谱版本结构、1–5 分评分表 | 前端无对应反馈入口；当前反馈仅克隆旧内容并保存 instruction；没有宝宝 liked boolean 或推荐反馈闭环 | 新增轻量喜好和真实历史；保留旧记录 |
| 冰箱存量 | 未见专门模型、API、页面或 Agent 工具 | 无份数、入库、分配、消耗、流水 | 新增 Fridge |
| 膳食指导 | 生成表单有口味/饮食字符串；有只读 preference 数据 | 无可管理 skill、规则版本、营养搭配检查；长期偏好没有编辑闭环 | 新增 Planning guidance |
| 时间预算 | 菜谱有 prep_minutes、cook_minutes | 不能等同于人工/等待；没有步骤依赖、设备并行、半天/每天预算校验 | 新增排程与时间模型 |
| 周五自动生成 | 有后台队列、执行、恢复基础 | 没有每周生成规则、草案调度和确认提醒 | 新增应用定时任务 |
| Agent | 有持久化 run、工具调用、菜谱/计划/todo 直接 CRUD，以及传统 suggested action 路径 | 工具名仍叫 ReadOnly，但实际含写入；缺少 Plan 内引用和范围理解、可编辑 guidance | 复用基础并统一新操作语义 |
| MCP | 有内部工具注册表和 HTTP API | 未见 MCP 服务；内部 tool registry 不能视作 MCP | 新增外部 AI 读写接口 |
| 语言 | 有整套中文/英文切换和用户内容原样展示 | 旧文档以一屏一种 UI 语言为原则 | 新界面统一英文，中文业务内容完整保留 |
| 分享 | 有分享 service、快照、token、API 和公开页面基础 | 旧文档完整管理能力需单独运行验收，当前不据此宣称全部完成 | 保留次级入口，本轮不扩张 |

## 3. 关键实现证据

### 3.1 计划可以保存，但还不是完整规划系统

- [计划页](../web/src/features/plans/plan-board.tsx) 第 30 行开始读取真实 plans 和 recipes；第 37 行仅提取已有条目日期；第 67 行手动保存餐次；第 111 行按日期纵向展示。
- [生成页](../web/src/features/plans/plan-generator.tsx) 第 62 行提交生成请求，结果状态明确为已保存。
- [规划服务](../src/recipe_agent/domain/planning/service.py) 第 65 行开始按餐型缓存三条推荐，第 84 行通过取模轮换；替换预览按 day 查找第一个餐次。
- [计划模型](../src/recipe_agent/domain/planning/models.py) 有计划版本和餐次，没有 Draft / Confirmed 或单餐执行状态。

### 3.2 推荐特征没有接到真实家庭数据

- [运行时推荐来源](../src/recipe_agent/bootstrap.py) 第 165 行的生成类只要求输出菜名；第 186 行为每个菜名分配 UUID，没有创建完整菜谱。
- 同文件第 202 行按家庭可见及餐型查询菜谱；第 223 行为候选使用固定 `_default_features()`，第 229 行定义固定分数。
- [评分函数](../src/recipe_agent/domain/recommendations/scoring.py) 虽定义原料、喜好、时间、重复等权重，但权重函数存在不代表实际数据已正确接入。

### 3.3 导入接口与真实文件解析有差距

- [输入适配器](../src/recipe_agent/domain/imports/adapters.py) 第 64/74 行的图片和 Excel 适配器仅返回文本及对象 key；第 84/94 行的链接适配器直接抛出未接 worker 的异常。
- [导入服务](../src/recipe_agent/domain/imports/service.py) 第 61 行仅将 `extracted.text` 交给模型。
- [聊天入口](../web/src/features/chat/chat-home.tsx) 的附件提示没有相应上传交互；[导入 API](../src/recipe_agent/api/v1/imports.py) 主要提供状态列表和详情读取。

### 3.4 待办、采购、库存不能混为一谈

- [Todo 模型](../src/recipe_agent/domain/todos/models.py) 记录 category、title、note、completed 和 due_on，没有备餐产出或库存关系。
- [采购聚合器](../src/recipe_agent/domain/planning/shopping.py) 有同名同单位求和逻辑，生产代码未形成生成采购清单的调用链。
- 已检查 `src`、`web/src`、`migrations`：未找到独立库存领域、份数消费及备餐入库实现。

### 3.5 当前 Agent 已可以直接写入

- [工具注册与执行](../src/recipe_agent/domain/conversation/read_tools.py) 第 290 行开始注册工具，第 458 行开始包含业务写入分支；菜谱、计划和 todo 均可直接修改。
- [反馈仓库](../src/recipe_agent/domain/feedback/repository.py) 第 92 行开始创建版本、克隆旧食材步骤、保存 instruction；没有将自然语言反馈真正应用为新的食材/步骤修改。

## 4. 文档与实现的主要分歧

1. **旧定位是 chat-first。** [PRD](./product-requirements.md) 将 `/chat` 设为默认入口；本次转为以每周日历执行为主。
2. **冰箱曾被明确排除。** PRD 末尾及原始设计的 Non-Goals 都排除了 inventory。本次是新增核心范围。
3. **只读 Agent 要求已过时。** [统一运行时设计](./superpowers/specs/2026-07-15-unified-react-runtime-design.md) 要求自然语言只读、点击才写；当前实现和 [历史 QA](../design-qa.md) 已支持直接写入。
4. **家庭模型经历变化。** 原设计是一账号一家；后续设计允许一家多个独立账号、记录保留 owner。新库存不能忽略现有数据范围。
5. **“完整 MVP”是原合同，不是当前功能事实。** 多份计划的未勾选状态也不能反过来证明没有实现；当前代码已经存在若干未勾选的恢复功能。
6. **测试与历史 QA 不等于本轮验收。** `design-qa.md` 曾报告五个视图、真实 AI 生成和 CRUD 通过；本轮未复跑。现有浏览器 E2E 使用 mock API，不能证明新的完整厨房流程可用。
7. **旧技术文件中的端点和界面说明有漂移。** 新 spec 应在产品和 demo 确认后统一更新，不能在本次产品稿里直接继承旧接口为最终合同。

## 5. 阅读覆盖

已读主目录 16 份 Markdown、隐藏目录 2 份阶段报告、6 份历史设计 HTML。对 worktree 的 16 份对应主文档副本做逐字节核对；内容相同，按同一份文档计算。

### 根目录和产品技术文档

- [README](../README.md)
- [Design QA](../design-qa.md)
- [Product requirements](./product-requirements.md)
- [Business plan](./business-plan.md)
- [Phase plan](./phase-plan.md)
- [Technical specification](./technical-specification.md)

### 设计

- [Family Recipe Agent design](./superpowers/specs/2026-07-15-family-recipe-agent-design.md)
- [Unified ReAct runtime design](./superpowers/specs/2026-07-15-unified-react-runtime-design.md)

### 实施和修复计划

- [Family Recipe Agent MVP](./superpowers/plans/2026-07-15-family-recipe-agent-mvp.md)
- [Unified ReAct runtime](./superpowers/plans/2026-07-15-unified-react-runtime.md)
- [Durable suggested actions review fixes](./superpowers/plans/2026-07-16-durable-suggested-actions-review-fixes.md)
- [Durable suggested actions rereview](./superpowers/plans/2026-07-16-durable-suggested-actions-rereview.md)
- [Queued dispatch reconciliation](./superpowers/plans/2026-07-16-queued-dispatch-reconciliation.md)

### 运维与验收流程

- [Deployment](./runbooks/deployment.md)
- [Failed jobs](./runbooks/failed-jobs.md)
- [Local end-to-end](./runbooks/local-end-to-end.md)

### 历史报告与设计页面

- [.superpowers/sdd/task-6-report.md](../.superpowers/sdd/task-6-report.md)
- [.superpowers/sdd/task-7-report.md](../.superpowers/sdd/task-7-report.md)
- `.superpowers/brainstorm/37999-1784159765/content/architecture-options.html`
- 同目录 `interface-design.html`、`interface-design-v2.html`、`lark-agent-loop-v3.html`、`waiting-architecture-approved.html`、`waiting-design-approved.html`

旧设计引用的源文件 `存菜谱AI_Agent_PRD_竞品调研版.docx` 未出现在当前项目文件清单中，因此不属于本次已读原文件；现有 Markdown 设计引用了它。

本次没有改动现有产品代码或旧文档。下一份可供确认的交付为 [产品重设计草案](./product-redesign-proposal-2026-09-17.md)。
