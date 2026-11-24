# 单制作室运行架构

部署方案包含两个容器。Caddy 接入公众试玩，FastAPI 提供制作和试玩接口，并在同一进程内启动后台执行器（worker）。SQLite 保存项目、任务和运营记录，游戏包与美术文件保存在同一数据卷。[启动入口](../app.py#L28) · [容器配置](../docker-compose.yml) · [部署决策](ADR/ADR-004-private-studio.md)

## 代码目录

应用代码集中在 [studio/application/](../studio/application/)。按你要改的事情找入口。

| 目录 | 要改的事情 | 从哪里读 |
| --- | --- | --- |
| `agents/` | 给角色分配技能、调用模型、固定技能版本 | [角色注册表](../studio/application/agents/registry.py) · [AgentScope 调用](../studio/application/agents/gateway.py) · [五份运行时技能](../studio/application/agents/skills/) |
| `harness/` | 安排执行顺序、恢复中断的任务、安排专家质询 | [生产流程](../studio/application/harness/production/workflow.py) · [交付物与负责角色](../studio/application/harness/production/nodes.py) · [运营专家讨论](../studio/application/harness/operations/debate.py) |
| `memory/` | 保存编辑者和项目偏好，控制各角色能看到哪些历史与证据 | [偏好读写](../studio/application/memory/preferences.py) · [按角色裁剪](../studio/application/memory/projection.py) · [冻结与回查输入](../studio/application/memory/snapshots.py) |
| `prompts/` | 改某个角色的系统指令，或给立项、迭代、复核增加要求 | [全局约束](../studio/application/prompts/base.md) · [角色指令](../studio/application/prompts/roles/) · [任务和阶段指令](../studio/application/prompts/tasks.py) |
| `tools/` | 改检索、生图、游戏打包或产物校验 | [调研](../studio/application/tools/research.py) · [生图](../studio/application/tools/image_service.py) · [构建](../studio/application/tools/cartridge.py) · [验收](../studio/application/tools/acceptance.py) |
| `usecases/` | 改团队或玩家可执行的动作，例如建游戏、批提案、开局、结算 | [游戏与版本](../studio/application/usecases/games/) · [人工决策](../studio/application/usecases/operations/decisions.py) · [玩家对局](../studio/application/usecases/gameplay.py) |

以修改美术师为例。调整它如何描述贴图，编辑 [ArtDesigner.md](../studio/application/prompts/roles/ArtDesigner.md)。改变它可以看见的偏好，编辑 [projection.py](../studio/application/memory/projection.py)。替换生成 PNG 的服务，编辑 [image_service.py](../studio/application/tools/image_service.py)。新增生产角色时，在注册表声明团队和技能，补同名角色指令，将交付物绑定到生产节点的输出契约。新工序的先后顺序由 [生产阶段表](../studio/domain/revision.py) 定义。

## 第一次读代码

从测试里的《回声航标》开始。先打开 `draft()`，里面的 `work()` 执行一项后台任务，`decision()` 模拟团队在制作台上的一次决定。跟到 `publish()`，可以看到试玩、验收和发布的先后顺序。[制作和发布示例](../tests/support.py#L78)

读这段代码时会遇到三个名字。`game` 是《回声航标》这个项目，`revision` 是它的一次制作或改版，`bundle` 是构建出的游戏文件包。每局试玩记录实际使用的版本和包，所以同一款游戏的旧版和新版可以同时做实验。[数据表](../studio/infra/migrations/baseline.sql) · [开局时选择版本](../studio/application/usecases/gameplay.py#L32)

| 跟着哪个动作读 | 代码怎样接下去 |
| --- | --- |
| 团队点「创建」 | 接口建项目和首个版本，将调研任务写入 `jobs`。worker 取出任务，交给 `produce()`。该函数按当前阶段检查还缺哪些产物，生成一项就保存一项，到人工确认处停下。[创建版本](../studio/application/usecases/games/revisions.py#L18) · [任务分发](../studio/application/harness/worker.py#L30) · [生产循环](../studio/application/harness/production/workflow.py#L25) · [阶段和人工操作](../studio/domain/revision.py#L3) |
| 轮到一个 Agent 工作 | 生产节点选定角色和预期输出格式，`consult()` 装入本次运行固定的指令、技能和可见上下文，通过 AgentScope 调用模型并校验结果。想改美术师收到的材料，先看节点。想改美术师共用哪份手册，先看角色与技能的对应表。[生产节点](../studio/application/harness/production/nodes.py#L46) · [模型调用](../studio/application/agents/gateway.py#L87) · [技能分配](../studio/application/agents/registry.py) |
| 上线后团队点「分析」 | 玩家完局产生观测记录。手动分析或每日批次冻结数据和对应源码，专家团据此形成提案。批准改版会创建同一游戏的新版本，回到第一条生产流程。实验到期后再结算效果，经验经审核生效。[冻结证据](../studio/application/usecases/operations/evidence.py#L19) · [专家讨论顺序](../studio/application/harness/operations/debate.py#L24) · [批准提案](../studio/application/usecases/operations/decisions.py#L14) · [结算](../studio/application/usecases/operations/experiments.py#L143) |

旧集成可以继续从 `studio.production`、`studio.operations` 等 v1 入口导入。`domain/revision.py` 定义阶段规则，`application/usecases/games/revisions.py` 处理审批和版本变更，`infra/repositories/revisions.py` 负责其 SQL 读写。

## 请求与数据边界

```text
玩家浏览器 ─── HTTPS ──► Caddy ───────┐
                                    ├──► FastAPI 路由 ──► 应用服务 ──► SQLite WAL
团队浏览器 ─── SSH 隧道 + 制作台口令 ───┘                        └──► 版本包与美术文件
                                              同进程 worker ──► AgentScope / 美术网关
```

网关按路径和 HTTP 方法放行样片、正式游戏包、对局事件、提示、评价和自然完局后的活动跳转。它清除入站制作台凭证。服务端对预览开局另查制作台身份，按已发布状态检查游戏包。所有玩家写入都限流，反馈进入模型上下文前按关卡和评分汇总。玩家请求本身只保存观测，生成任务来自团队操作或后台日批。

| 应用层以外的目录 | 边界 |
| --- | --- |
| `app.py`、`studio/api/` | FastAPI 装配、团队登录、HTTP 入参和响应 |
| `studio/domain/` | 生产阶段、输出契约、证据校验和指标计算 |
| `studio/infra/` | SQLite 读写与迁移、报表、文件读写、QuickJS 运行与备份 |
| `studio/web/`、`studio/engine/` | 浏览器制作台与玩家界面、共用游戏宿主和运行素材 |

## 13 个角色怎样协作

程序决定合法节点、可引用的证据和人工门禁。每次模型调用通过 AgentScope 的 `Agent`、`OpenAIResponseModel` 与角色系统提示执行，角色之间显式交接材料。角色数描述不同职责，同一角色会在不同阶段重复调用。

| 链路 | 角色 | 编排与验收 |
| --- | --- | --- |
| 生产，8 个 | Producer、GameplayResearch、Planner、ArtDesigner、LevelDesigner、GameCoder、LevelCoder、QualityReviewer | 制作人调度，先选图和方向，再审批设计；玩法、关卡程序分别生成。构建器检查实际发布模块，独立评审与团队试玩过关后发布 |
| 运营，5 个 | Analyst、Engineer、GameDesigner、Reviewer、Moderator | 同版本事实分别裁剪后交给专家。工程师要给出源码引用。质询须指向责任人，主持人逐项裁决，评审逐项复核，未解决的分歧退回补证 |

**存量改版**冻结观察窗、正式对局、源码、关卡包及探针。四位专家各自首评，每次分析最多同时调用三个角色。评审读完首评提出反例，各责任人回复，主持人形成带目标值与期限的提案。人工批准后建立子版本，发布时核对批准的基线与改动。参数实验重建完整预期关卡，并比较依赖字段及其余关卡。旧包只在能复现其原蓝图时参与参数验收。

**新游立项**先让分析师、评审、工程师形成受众约束、已知死路审计和工程可行性记录；三份到齐后设计师交付 2–3 个候选。分析师挑战候选，主持人选定一个并记录淘汰理由，评审复核重合与证据。提交时和人审批准时都会核对候选引用是否对设计师可见。

**生产检查点**依次经过调研、选参考、逐图分析、选方向、设计、方案审批、构建、试玩验收、待发布。版本号与阶段同时校验，陈旧审批返回 409。任务按节点保存产物，重试复用已完成节点，修改蓝图会使原构建试玩失效。SQLite 串行化写事务，耗时的模型调用与对局回放在写事务外运行。

## 原案例五层怎样验收

| 层 | 项目中的落点 | 团队能核对什么 |
| --- | --- | --- |
| L1 感知 | `infra/reporting.py`、`application/usecases/operations/evidence.py` | 游戏与关卡报表使用同一观察窗，样本能对应到正在分析的版本 |
| L2 决策 | `application/harness/operations/debate.py`、`domain/deliberation.py` | 每个争议有责任人、证据和处置，证据不足可以明确退回 |
| L3 执行 | `application/harness/production/workflow.py`、`application/harness/production/nodes.py` | 人能看到受影响的产物、重新验收的版本和实际工序记录 |
| L4 基座 | `application/tools/cartridge.py`、`infra/game_runtime.py`、`web/play-host.js` | 多个小游戏共用宿主，同一构建能重放真实对局 |
| L5 治理 | `application/usecases/operations/experiments.py`、`application/memory/snapshots.py`、`application/agents/skillbook.py` | 一次改动可从批准、分流、到期结果追溯到生效知识和下次注入 |

## 上下文、记忆和技能

每次生产或分析记录项目偏好版本、近期决定和生效知识。新建游戏继承该浏览器编辑者的偏好，项目设置可以覆盖。角色只读取相关字段。工程师与评审可读冻结源码，设计师读取可见指标与工程结论。模型收件材料、系统提示、图像字节摘要和技能版本可从私有制作台复核；输入预算为 160,000 字节。待补证记录和未验证知识具有独立状态。

五份项目手册由 AgentScope `LocalSkillLoader` 加载。玩法设计、可玩关卡、实验评审按角色注入，存量改版和新游立项手册按任务追加。首次执行固定模型、手册正文 SHA-256，以及每个角色在本次任务中使用的有序技能清单。节点首次调用时保存系统提示和输出契约。在途任务续跑沿用归档的分配；升级前的任务按 v1 已发布的分配读取原有技能正文。[技能绑定](../studio/application/agents/skillbook.py) · [旧版分配记录](../studio/application/agents/v1-skill-routes.json)。开发机的 AgentScope 开发 skill 供工程人员查阅，运行镜像携带项目手册。[技能表与注入实现](../studio/application/agents/skillbook.py) · [节点提示](../studio/application/prompts/builder.py)

## 从试玩回到运营

游戏共享宿主的配置查询、开始、结束、提示、反馈和活动跳转。新构建的 `level.json` 记录 Seed 以及每关的生成参数或完整预制布局，蓝图接口、玩家宿主与服务端回放读取相同的输入。构建时逐关比较显式传参与独立模块内置配置的结果。自然完局的成绩由服务端在开局锁定的版本上重放输入验证。按游戏、版本、构建和观察窗产生三级报表。到期实验先核对交付，再计算观测差值并检查样本及干扰；由团队决定全量或回退。样片与草稿试玩独立于正式指标。活跃、留存和点击率都以各自分母解释。[七图验收](ACCEPTANCE.md)

轻量机使用单 Uvicorn worker，最多同时执行两个后台任务，其中最多一个运营分析任务。制作室上限为 50 款游戏、每款 200 个版本和 20 个活动入口，每天最多新建 20 个分析提案。新游戏包的未压缩文件合计上限为 5 MiB。个人账号、按成员授权、跨团队隔离和用量计费属于未来的外部制作平台方案。[产品范围](ADR/ADR-004-private-studio.md)

## Agent 工程的八项验收

| 章节 | 运行时约束 | 改动后怎样验证 |
| --- | --- | --- |
| 上下文工程 | 先冻结构建、证据和项目偏好，再把证据目录投影到每个角色。分析师可以引用指标和团队补证，工程师与评审还可以看到实际源码。历史样本可按预算裁剪，当前源码和外部干扰证据必须完整。可用节点输入摘要反查实际系统提示、技能版本和图片摘要 | 修改角色或证据类型时，同步维护字段投影、来源目录及隔离用例。[上下文规则](../studio/application/memory/projection.py) · [证据目录](../studio/domain/evidence_sources.py) · [隔离回归](../tests/test_release_integrity.py) |
| 流式输出 | 调研期间只发布顶层摘要的临时快照。团队页面用 EventSource 订阅当前版本。重连用 Last-Event-ID 读最新状态，新的阶段或交付物才触发页面重新取数。旧版本序号的写入失效，登出后关闭订阅。最终报告须经过产物校验 | 用两个消费者分别验证重连和会话撤销，再在浏览器确认草稿出现时整份项目只下载一次。[解析器](../studio/application/agents/streaming.py) · [进度查询](../studio/application/usecases/games/progress.py) · [浏览器验收](../tests/browser/smoke.mjs) |
| 项目配置 | 应用启动时校验环境。文字服务默认 GLM 5.4，文本与图像凭据独立。图像模式可显式选 Responses 网关或本地渲染。模型地址、空目录和不合法开关在启动时给出错误 | 新增配置须覆盖缺省值、错误输入、私密字段的日志表示和升级行为。[配置入口](../studio/settings.py) · [环境示例](../.env.example) |
| 工具设计 | 调研区分离线、空结果、部分成功与服务不可用。生图网关先接收临时产物，收到完成事件并验收 PNG 后才写缓存。重用时核对请求、父图、模型与图片摘要。仅修改 UI 音轨时保留原贴图、节拍和其他轨道 | 工具测试覆盖中断、拒绝、返回错误数据、缓存错配和重试。新增依赖实体还要验证受影响的下游。[调研工具](../studio/application/tools/research.py) · [图像适配器](../studio/infra/image_response.py) · [资产生产回归](../tests/test_production.py) |
| 效果评测 | 固定样例验证证据可见性、立项候选差异及实验归因。玩家点击和 D1 的分母、95% 比例差区间由结算代码计算。在线用例通过同一 AgentScope 入口检查局部改动、识别干扰和死路审计 | 执行 `python -m scripts.evaluate_agents`。更换云模型、角色提示或技能时执行 `python -m scripts.evaluate_agents --live`，记录数据集摘要、模型和技能清单。线上留存或转化仍按实际预注册实验验收。[样例](../evals/studio-v1.json) · [结算规则](../studio/domain/evaluation.py) |
| 部署观测 | 就绪状态同时检查数据库可写、磁盘、队列和当选执行器心跳。每次实际的文本模型请求按角色、供应商和结果计数，校验失败与重试分别记录。使用量按供应商实际报告累计 | 在团队口岸检查 `/readyz` 和 `/metrics`。可按角色发现大量格式修复、供应商失败或耗时上升。[健康与指标](../studio/infra/monitoring.py) · [运行手册](RUNBOOK.md) |
| Harness 工程 | 本地与 CI 共用离线验收入口，覆盖分层、格式、前端路由、内联脚本、Shell、业务评测和回归。Linux 继续验收 Compose、Caddy、真实浏览器及从备份恢复 | 在仓库根目录执行 `python -m scripts.check`。涉及容器、公开入口或玩家交互时，还需对应的 Linux 作业通过。[统一验收](../scripts/check.py) · [CI](../.github/workflows/check.yml) |
| Agent 自进化 | 方案预注册后先核对实际交付，再按样本和干扰判定归因。候选结论保存实际改动、指标、反证条件和结算证据。审核意见、生效与被替代的时间单独留痕。同一事务内复核被替代的知识须属于同一游戏并且仍然生效。历史观察窗仅能检索截止时已获准的经验和已发生的死路 | 回放一条经验在待审、采纳、被替代三个时间窗的可见性。升级前缺少审核时间的旧记录从迁移时点起可检索。已保存的旧提案保留原快照。[审核用例](../studio/application/usecases/operations/decisions.py) · [数据库迁移](../studio/infra/migrations/migrate_003_agent_engineering.sql) · [工程回归](../tests/test_agent_engineering.py) |

制作人修改影响范围时，单独重绘已有实体只需重做相应美术产物。新增实体还会更新 GDD 和玩法代码，使资产清单与引用一致。每次改动仍经过构建、独立质量评审和试玩门禁。五份项目手册随运行固定。更新手册后的新任务会采用新正文，已开始的任务可继续读取原版。[生产编排](../studio/application/harness/production/workflow.py) · [技能版本管理](../studio/application/agents/skillbook.py)
