# 回路制作室（Loop Atelier）软件需求规格说明（SRS）

版本：v2.2（公网服务基线 · 注册与审批门版）｜ 日期：2026-11-23 ｜ 状态：待评审
适用范围：`app.py` + `studio/` + `studio/web/` + `studio/engine/` + `tests/` + `deploy/` + 打包链路。
上游依据：`docs/ACCEPTANCE.md`（当前工程验收，行为基线）→ `docs/PILOT.md`（试点与经营口径）→ `docs/original/01-全文整理.md`（原案例设计语言，`assets/img-06~img-60` 共 60 图）。
阅读规则：**与本文冲突时以本文为准并提 ADR**；本文只定需求与验收口径，不复述实现细节（实现见 `ARCHITECTURE.md`，验收证据见 `ACCEPTANCE.md`，历史快照见 `REVIEW-INITIAL.md` 仅作对照）。
版本历史：v1.0 单机重构基线（已归档，被本版取代、语义合并）；v2.0 新增公网视角；v2.1 把原案例 60 张设计图的可落地语义全部绑定到需求条目；**v2.2（本版）补齐注册机制与三权分立：匿名玩家 / 注册玩家 / 开发维护者 / 平台运维四类身份正交，玩家请求上云后必须经维护者审批（FR-12 + R-REQ + §8.2b）才允许进入 AI 迭代**。

---

## 本次交付范围

阿里云轻量服务器版采用内部团队制作、公众试玩的范围。本文涉及注册工单、多工作空间、按成员授权、商业 API 与旧平台打包的条款，保留作外部创作者平台的设计记录。本期部署与验收按 [ADR-004](ADR/ADR-004-private-studio.md) 及 [运行架构](ARCHITECTURE.md) 执行。

## 1. 背景与目标

### 1.1 一句话（对齐原案例 img-06 副标题）

把「**创意进 → 游戏出 → 数据回流 → 方案再迭代**」的全链路自迭代小游戏工作台，做成**别人可以直接用的外部服务**：创建者开工作室做游戏，玩家点链接即玩，运营数据回流成下一轮**可证伪、可结算、可归因**的迭代提案。人只做两件事（定义北极星指标与行动边界、审核关键方案），其余在边界内闭环。

原案例口径校注（不可混用，详见 `original/01-全文整理.md` 附录 B）：生产侧「2 周 6 款、最快平台内 ~1 小时、含验收到上线最快 2 天」；运营侧「首周 12 款、方案到上线 3 天、累计 20+ 次迭代、95%+ 正向 / 40%+ 全指标正向」；图 3 为 2026-08 单月口径（5 类型 / 9 新游 / 12 款迭代 / 20+ 次）。**本 SRS 不承诺复现上述数字**，只承诺复现其背后的工程机制（上下文流转 + 决策闭环），并以 `PILOT.md` 的试点方法重新计时验证。

### 1.2 v1 工作室版的两种运行方式

| 形态 | 监听与入口 | 鉴权 | 用途 |
| --- | --- | --- | --- |
| **单机/自托管** | `127.0.0.1:7860` | 无口令可本机试用（现状行为保留，仅限 `STUDIO_DEPLOYED != 1` 且监听本地时） | 本地试玩、开发联调、回归测试 |
| **阿里云轻量服务器** | Caddy 对公网开放 80、443，宿主机制作台绑定 `127.0.0.1:7860`，使用持久卷 | 团队通过 SSH 转发与制作台口令登录。玩家免登录试玩已发布游戏 | 内部团队制作、公众试玩和活动效果验证 |

公网形态硬要求：密钥走运行时环境注入（永不进包/进库/进日志）；`GET /healthz` 为存活探针，`GET /readyz` 为就绪探针（DB 可写 + 卷剩余 + 队列深度三项，任一失败即 NotReady）；单 worker（`workers=1`，SQLite WAL + 文件锁选主，见 ADR-002）。

### 1.3 v1.0 已诊断的问题（结论保留）

`app.py` 1096 行（路由+鉴权+Schema+业务+回放）、`studio/operations.py` 1149 行（报表+冻结+评审+结算+日批）、`studio/production.py` 790 行（状态机+Agent 调度）是混乱根源；`store.py` 只有裸 SQL helper；`studio.js` 1708 行散写 URL；`test_studio.py` 1384 行大单测。功能已闭环、工程结构未闭环。分层铁律不变：

> `routers → services → domain`；`infra` 只被 `services` 调用；`domain` 禁止 `import sqlite3/fastapi/httpx/agentscope/quickjs/os.getenv`。

### 1.4 v2.1 新增目标（公网可用的 Definition of Production-Ready）

1. **可隔离**：不同创建者的数据、密钥消耗、构建产物互相不可见；删号删空间可执行（软删 30 天 → 硬删 + 对象 GC）。
2. **可设防**：口令/会话/密钥/玩家入口四条链路分别有认证、限流、审计；密钥永不进包、进库、进日志（只存哈希，只记前缀）。
3. **可限流限费**：模型调用与生图调用有并发上限、单空间日预算、超限显式失败（429 配额 / 402 预算，不静默吞错、不透支）。
4. **可观测可恢复**：健康/就绪探针分离；结构化日志 + 指标 + 任务审计 + 费用归因；备份 = 数据库 + `builds/` + `generated-art/` 三件套，可演练恢复（RPO ≤24h、RTO ≤4h）。
5. **可演进**：Phase-1 单实例 SQLite 设 explicit 上限并可运行；Phase-2 切 Postgres + 对象存储时只换 `infra`，不碰 `domain/services` 契约（ADR-002）。
6. **可证伪可归因**（对齐 img-56/img-58）：每个运营提案都是带预测区间与证伪条件的一次「下注」，到期对照结算；知识分层（判断层/方法层/执行避坑），记忆四层（核心规则/知识/历史/会话）带治理元数据。

非目标（v2.1 仍不做）：微服务拆分、自研计费支付、第三方 OAuth 登录（预留接口）、多地域容灾、重写前端框架、3D/任意引擎插件。

---

## 2. 术语与角色

v1 上线范围由 [ADR-004](ADR/ADR-004-private-studio.md) 确定。表中 Workspace、User、RegisteredPlayer、Maintainer、PlatformAdmin 及后续章节对应的注册、工单、计费和跨空间接口均为未来平台设计。当前团队共享一个工作室，拥有可单独退出或通过轮换口令统一撤销的会话。

| 术语 | 含义 | 代码锚点 |
| --- | --- | --- |
| Game / Revision / Stage / Bundle / Round / Proposal / Experiment / Knowledge / 冻结证据 / checks / Skill | 沿用 v1.0 定义 | `studio/store.py:init`、`studio/settings.py`、`studio/deliberation.py:Check`、`studio/acceptance.py` |
| **L1–L5**（img-06） | L1 数据感知 → L2 运营决策 → L3 生产执行 → L4 游戏容器与模板 → L5 治理与自进化；顺时针回流到 L1 | 映射见 §4.1（本系统 L1=`operations` 报表+冻结，L2=`operations/deliberation` 主持人+专家团，L3=`production` Producer+6 Agent，L4=`cartridge/engine/web` 宿主+MF+双模式关卡，L5=`worker` 日批+门禁+知识/记忆沉淀） |
| **Producer + 6 Agent**（img-14/img-15） | `GameplayResearch → Planner → ArtDesigner → GameCoder → LevelDesigner → LevelCoder` + 独立 `QualityReviewer`；Producer 是唯一调度者，全局状态串联上下文 | `studio/production.py:STEPS/NEXT`、`studio/agents.py` |
| **Workspace（工作空间）** | 公网计费与隔离单元：一组人、一组游戏、独立配额与 API Key。现状缺失，v2.1 新增 | 新增表 `workspaces/members/api_keys`（§10） |
| **User（注册用户）** | 邮箱 + 口令注册的自然人身份。全平台唯一，可归属多个空间。`users(id,email,pass_hash,status,created)`，`status: active/suspended/deleted` | 新增；现状无，P6 落地。匿名 PlayerID 不等于 User |
| **RegisteredPlayer（注册玩家）** | 用 User 身份登录玩家端的玩家：可跨设备同步进度、可提交带身份的反馈/工单、可查自己的请求处理状态。沿用站内玩家标识 | `rounds.player` 绑定 `user_id`（可空，匿名时为空）；`feedback.reporter=user_id` |
| **AnonymousPlayer（匿名玩家）** | 未登录玩家：浏览器随机 `loop-player` 标识，仅本机去重与分流。**只能玩游戏 + 提交匿名反馈，不能查处理进度、不能进实验白名单、不能调任何特权接口** |现状 `Player` 正则即此；保留 |
| **Maintainer（开发维护者）** | 空间内 `owner/editor/viewer` 三档。`owner` 管成员/密钥/删除/冻结；`editor` 做游戏/批方案/触发分析/处理玩家请求；`viewer` 只读报表与证据，不可批准 | 替代单一 `STUDIO_ACCESS_KEY` 共享口令（§9.3 矩阵） |
| **PlatformAdmin（平台运维）** | 跨空间只读健康/指标/费用 + 紧急冻结违规空间。**不能读空间内游戏源码与玩家原文（隐私隔离），只能看脱敏指标与审计摘要** | `metrics` + `audit_log` 摘要权限 |
| Session | v1 每次登录签发独立的随机凭据，库中保存带密钥的摘要，12 小时到期，退出或轮换口令可撤销 | `studio/api/auth.py` |
| PlayerID | 浏览器随机匿名标识（`loop-player`），仅用于分流与去重，不做跨站追踪 | `studio/web/play-host.js:playerId` |
| 公共链路 / 特权链路 | 公共：开局/事件/反馈/跳转/已发布包；特权：建游戏/改方案/看报表/批提案/触发分析 | §9 分组，公共链路免登+强限流，特权链路鉴权+审计 |
| **冻结证据**（img-55 门禁①） | 分析前一次性快照：观测窗 + 版本 + 构建哈希 + 分母 + 源码 + 关卡参数行 + 反馈 + 知识引用；V1 样本禁配 V2 源码（R-EVIDENCE） | `studio/operations.py:freeze` |
| **可证伪下注**（img-56） | 提案必须写预测区间、引用知识 ID、证伪条件；到期对照「实际交付了什么」再取数 | `studio/deliberation.py:Proposal`、`studio/operations.py:settle` |
| **四层记忆**（img-58） | 核心规则（常驻注入）/ 知识（按游戏+玩法召回）/ 历史记忆（事件唯一可引用证据）/ 会话记忆（断点续跑） | `studio/context.py`、`studio/skillbook.py` |

北极星指标（5 选 1，不变）：`win_rate` / `rounds_per_player` / `seconds_per_player` / `action_rate` / `d1_rate`。`d1_rate` 为成熟 D1 队列口径（`operations.py` 留存队列），其余四项见 `settings.py:METRICS`。

---

## 3. 干系人与用户故事（公网视角）

- **游戏创建者**：注册（邮箱+口令，见 FR-9.1）→ 建空间 → 填创意/北极星/边界 → 走生产门禁 → 发布 → 发活动链接 → 看漏斗 → 批迭代。期望：我的游戏别人看不见；模型费用可预期；误操作可回退（`revise` 按 `invalidated_artifacts` 精确失效）。
- **匿名玩家**：点链接即玩，无需注册；断网/切后台不丢已提交对局；完局后可点活动按钮、可提交匿名评分+短评（只进证据池，不直接触发 AI）。期望：加载快、无登录墙、不被追踪（PlayerID 仅本游戏去重）。
- **注册玩家**：用邮箱注册登录后可跨设备同步进度、提交带身份的问题/建议工单（`player_requests`）、查询自己工单的处理状态（已受理/已采纳/已拒绝+理由）。期望：我的建议有人看、有回音；不被别的玩家看到身份。**注册玩家仍不是维护者：不能触发分析、不能批提案、不能看内部评审。**
- **开发维护者（空间 owner/editor）**：处理玩家请求收件箱（去重/合并/接受/拒绝均留痕）→ 只有被接受（`accepted`）的请求才允许进入下一轮 AI 分析证据；拒绝必须写理由。期望：垃圾/重复/恶意请求不进 AI（省钱）；每条采纳可追溯到版本与结算。
- **空间管理员**：管成员、轮换密钥、设预算、导出/删除数据。期望：离职成员一键移除；密钥泄漏可吊销（60s 内全实例生效）；账单可对账（`usage_ledger` 按 Token/图/字节/流量四类记账）。
- **平台运维**：看健康/指标/任务积压/费用，处理漏批与僵尸任务，做备份恢复。期望：报警先于用户投诉（一页恢复，见 `RUNBOOK.md`）；RTO ≤4h。
- **安全/合规**：审计谁批了什么、证据快照是否可重放、违规内容是否可下架。期望：所有人工批准留痕（`history` + `audit_log` 双记）；违规游戏可冻结公共入口（包保留用于举证）。

---

## 4. 系统全景（L1–L5 绑定需求）

### 4.1 逻辑架构（v1.0 延续 + 公网横切 + 原图绑定）

```text
浏览器：studio.js(制作台) / play.html+play-host.js+frame.html(玩家沙箱)
  ▲ HTTPS/JSON ── 反代层（TLS/限流/静态缓存，见§12，Caddy 或平台网关）── ▲
┌ API 层 api/：studio · player · ops · assets · admin(成员/密钥/空间) · public_v1(外部API) ┐
├ 应用服务 services/：production · gameplay · operations · review · experiment · knowledge │
│  preference · batch · workspace(成员/配额) · billing(用量记账) · moderation(审核/冻结)   │
├ 领域 domain/（纯函数，无 I/O）：revision_machine · evidence · deliberation_protocol    │
│  acceptance · metrics · settlement · level_rules · art_policy · ab_assignment · quotas  │
├ 基础设施 infra/：sqlite_store→Repository · cartridge_fs · quickjs_runtime               │
│  agent_gateway · art_gateway · research_gateway · skill_store · job_queue · object_fs    │
└ 横切：config(settings, 环境矩阵) · authn/z(session+API Key+RBAC) · schemas · logging    │
    · metrics · request_id · rate_limit · audit(history) · secrets(只读环境)              ┘
```

**L1–L5 到本系统的需求绑定**（对照 `original/assets/img-06.png`）：

| 原图层 | 本系统承接 | 需求要点 |
| --- | --- | --- |
| L1 感知层「看见发生了什么」 | `services/batch` 日批 + `domain/evidence` 冻结 | 数仓 T+1（北京时间 08:00 后处理上一自然日）；三级报表（中心/游戏/关卡）+ AB 视图同一口径；整批门禁：核心报表失败则**中止整批**（§8.3 门禁①） |
| L2 运营决策层「只分析，不执行」 | `services/review` 主持人+专家团（`deliberation_protocol` PROTOCOL=3） | 独立首评隔离锚定 → 评审质询 → 主持人收敛 → 人审；只有主持人有收敛权；任务类型含迭代/立项/结算/对账（§5 FR-4/FR-5） |
| L3 生产执行层「只执行，不分析」 | `services/production` Producer + 6 Agent（§5 FR-1/FR-2） | 玩法调研（以图收敛）→ 策划（高密度 GDD）→ 美术/音频（三层锚点）→ 游戏编码 → 关卡设计（5 章 spec）→ 关卡编码；上下文自动串联，人只在选图/批方案/验试玩三处介入（img-15 四决策） |
| L4 工程基座「让 Agent 只写差异化逻辑」 | `infra/cartridge_fs` + `infra/quickjs_runtime` + `studio/engine` + MF 宿主 | 三层容器（调度/容器服务/AI Agent，img-43）；固化壳（Phaser+React 脚手架/Controller/通用接口）+ 可变层（对象/主场景/关卡数据）；关卡双模式 runtime/prefab（img-32）；宿主三通道 `queryGameConfig` + 生命周期 + `app:event/host:event`（img-37/img-38） |
| L5 治理与自进化层「能用工程回滚，不依赖提示词」 | `services/knowledge` + 四层记忆 + `services/batch` 结算归因 | 硬门禁（无证据不得推进，R-EVIDENCE/R-REVIEW/R-RELEASE）；知识分级（已验证/未验证/已失效）；可证伪下注 + 三层归因（假设错→判断层，方法错→方法层，执行错→避坑，img-56）；记忆治理元数据（作用域/证据/等级/置信度/版本链，img-58） |

三原则（img-06 底部，原样继承为需求约束）：**判断与执行分离**（L2 不写代码、L3 不做归因）；**硬约束进代码，不靠提示词**（所有门禁都是 `domain` 纯函数 + 单测，非 prompt 约定）；**交付的不是结论，是可证伪的下注**（无预测区间/证伪条件的提案不得送审）。

### 4.2 运行时拓扑（公网形态）

```text
CDN/反代(缓存 /cartridges/v1/* immutable + 静态) ──► FastAPI(7860, workers=1 起步)
  ├── 同进程 worker.serve()(文件锁选主，心跳15s，僵尸180s回收，attempts≤2)
  ├── SQLite WAL 卷(/mnt/workspace 或 STUDIO_DATA_DIR) + builds/ + generated-art/
  ├── 出站：Z.AI Responses(文本/多模态) · 美术网关 Responses(image_generation) · Commons检索
  └── 可观测：/healthz(存活) /readyz(就绪：DB+卷可写+队列深度) /metrics(特权+内网)
```

Phase-2（ADR-002）允许把 `sqlite_store` 换成 Postgres、`cartridge_fs/object_fs` 换成 S3 兼容存储，`services/domain` 契约不变。切换开关只有 `DATABASE_URL` / `OBJECT_STORE_*`，为空即 Phase-1 模式。

### 4.3 当前 → 目标映射（v1.0 保留 + 公网增补）

| 当前 | 目标归属 | 公网增补 |
| --- | --- | --- |
| `app.py` 路由+鉴权+Schema+业务 | `app.py`(组装<120行) + `api/*` + `api/schemas.py` + `api/deps.py` | 新增 `api/admin.py`（空间/成员/密钥）、`api/public_v1.py`（外部 API 版本化）；`deps.py` 加 API Key + RBAC + 限流依赖 |
| `store.py` 裸 SQL | `infra/sqlite_store.py` Repository | 新增 Workspace/Member/ApiKey/Usage/Audit Repository；SQL 只允许在此层 |
| `worker.py` 调度+认领+巡检 | `infra/job_queue.py` + `services/batch_service.py` | 队列深度/最老等待指标；模型/生图两条独立并发信号量；预算检查进队前置 |
| `settings.py` 直读 env | `config/settings.py` | 环境矩阵校验启动即失败（缺必填项不裸奔，见 §12）；`os.getenv` 只允许在 config 层 |
| 打包 `package_studio.py` | 清单同步 `api/services/domain/infra/config` | `.env/.venv/data/*.sqlite3/__pycache__` 永不进包；加 SBOM/镜像扫描（§12） |

---

## 5. 功能需求（FR）

### FR-1 游戏立项与生产（主链，沿用 v1.0 + 公网约束 + img-14/15 绑定）

- FR-1.1 创建游戏归属空间，`request_id` 幂等；跨空间 `request_id` 不互认。`request_id` 缺失的写操作服务端生成并回显，客户端重试必须携带。
- FR-1.2 生产状态机 `serial` 乐观锁，过期 409；非法转移拒绝（转移表见 §8.1）。`serial` 每次写操作 +1，读-改-写必须回显最新值。
- FR-1.3 人工门禁链不变：**选参考图(1–4)→选方向→批方案→试玩验收（当前构建自然完局+服务端回放一致）→发布**。对应 img-15「设计→审核→确认」与「Human-in-the-loop」三类暂停点（方向选择/方案确认/质量验收），其余全自动。
- FR-1.4 返工只失效受影响产物；`serial+1`；`merge_assets` 语义保留。返工范围由 Producer 按 `invalidated_artifacts` 计算（策划/美术/关卡/代码四域），人确认后执行；新增实体必须走资产增量门禁（R-ART）。
- FR-1.5 构建产物清单不变（`game.js`、`level-generator.js`、`Level_Pack.json`、`Core_GDD.md`、`Difficulty_Config.csv`、`asset.json`、音视频、`manifest.json`、`remoteEntry.js`）；蓝图重建旧试玩失效；**包大小与关卡数上限显式化**（默认单包 ≤5MB、关卡 ≤12，超限 422）。
- FR-1.6 六 Agent 输入输出契约（对照 img-14，Producer 统一 Structured Output 路由，上下文自动串联）：

| Agent | 输入（上游产物） | 输出产物 | 门禁 |
| --- | --- | --- | --- |
| GameplayResearch | 创意文本 + 候选截图 | 调研报告（多检索词 + 逐图观察 + 规则来源 + 2–3 张参考图 + 玩法方向候选） | `reference_ids` 非空去重且命中本次选中（R-REF）；外部命中随关键词变化必须如实展示来源 |
| Planner | 调研报告 + 方向 | `Core_GDD.md`（高密度，每段可映射到开发动作）+ `Difficulty_Config.csv` | 无商业化独立结构化产物之前，商业化只记 GDD 文本段，不进验收 |
| ArtDesigner | GDD 资产清单 + 三层锚点（Base/Style/Entity） | `asset.json` + PNG/WAV（`asset_id` 全集一致，新增 `reference` 无环） | R-ART：实体 ID 集一致，未计划实体付费前拦截；生图发父实体实际 PNG |
| GameCoder | GDD 玩法段 + `asset.json` | `game.js`（状态/输入/绘制，QuickJS 可执行） | QuickJS 0.9s/24MB/512KB 栈；无 DOM/无 import |
| LevelDesigner | GDD 关卡章 + GameCoder 接口 | 5 章关卡 spec（gameType/数据结构/生成方式/验证方式/难度曲线） | R-BLUEPRINT：trail 连通 + 参数边界（`check_curve`） |
| LevelCoder | 关卡 spec | `level-generator.js` + `Level_Pack.json`（含可解性验证记录） | 同 Seed 确定性；trail BFS 真机逐格验证 |
| QualityReviewer | 全产物 + 构建证明 | 阻塞项清单（可空） | 任一阻塞项 → 打回程序员（有次数上限的返工），不带病发布 |

### FR-2 玩法调研与多模态（沿用 v1.0）

检索 → 人选图 → 实际图像字节 DataBlock → 逐图观察 + 规则来源 + 方向 → 下游。`reference_ids` 非空去重且命中本次选中集合，否则构建前拦截。图片按实际送模 JPEG 字节归档，规则检索结果单独检查点；外部网站变化后重试仍用冻结资料（可复现）。

### FR-3 关卡、蓝图与宿主回放（沿用 v1.0 + 公网加固，对齐 img-32/img-37/img-38）

- 双模式 runtime/prefab（img-32）：**A 难度因子配置**（代码内置梯度，运行时 `Rng(seed)` 现场生成，适合轮次/操作闯关类）；**B 内置预制关卡**（离线 `Rng(seed)` 生成候选 → 可通过性校验 → 不合格重试 → 评分择优，运行时只消费静态数据，生成链不进线上 MF 包，适合地图跑酷/推理求解类）。两种模式共同遵守 MF 契约：宿主默认只下发**当前关卡数 & 总关卡数**，游戏按进度本地生成或消费预置。
- 同 Seed 一致性：相同种子重复生成必须逐字节比对一致，否则构建失败。
- trail BFS 真机逐格验证；发布前逐关核对 + 2 Seed 抽检；蓝图与运行时复用同一条生成链（蓝图所见即玩家所得）。
- `POST /api/rounds/{token}/event` 自然完局必须带输入；服务端同 bundle 同关卡回放，`done/won/score` 三元组不符 422。
- 宿主三通道（img-37）：① `queryGameConfig` 通用异步查询（游戏问/宿主答，宿主自由决定来源）；② 生命周期回调 `onReady/onGameStart/onGameEnd`（游戏→宿主单向）；③ 双向事件 `app:event`（上行 `emit`）+ `host:event`（下行 `ref.sendHostEvent`）。`frame.html` 现有 CSP（`default-src 'none'` + Worker 沙箱）保留并扩展到全站基线（§7)；`sandbox="allow-scripts"` 不放宽；`postMessage` 保留 `loop=nonce` 校验。
- 三层容器（img-43）：调度层（LangGraph/Producer 编排 + Socket.IO 指令）/ 容器服务层（依赖安装 + dev server + Git）/ AI Agent 层（真实工作区文件操作）。本系统现状为单进程 + QuickJS 沙箱即等价实现，Phase-2 需远程容器时接口不变。

### FR-4 运营分析与实验（沿用 v1.0，四条反例为回归红线，对齐 img-51/img-55/img-56）

- 报表同一口径（三级：中心/游戏/关卡 + AB 视图，`operations.py` 单一实现）；冻结证据版本一致（禁 V1 样本 + V2 源码错配，R-EVIDENCE）；四首评隔离（独立会话 + 同一版冻结事实 + 不见同行意见）；质询闭环（任一 open/未通过 → `needs_evidence`，重大异议不可被摘要丢弃）；人审后子版本；开闸 `validate_release`（参数原值=control 实值、目标值=treatment 实值、回放一致、资产变更核对）；到期结算（变更 + 区间 + 样本门槛 + 外部干扰，样本不足 `delta=null` + 未验证）；证伪逐条指定（引用知识逐条裁决，不批量连坐）。
- 每日定时（img-55）：北京时间 08:00 触发 → ① 数据准备整批门禁 → ② 纯规则优先级（当日 top-N）→ ③ 结算任务 → ④ 新游戏上线对账 → ⑤ 分析任务（立项 ≤1 + 迭代 ×top-N）→ 产出验收（验真实交付物状态，不信 Agent 自报）→ 待评审队列 → 人工评审 → 确认执行。旁路：每 30min 巡检（僵尸/漏跑/假完成续跑）；验收未过同会话续跑（限次），预算耗尽标失败转人工。四门禁见 §8.3。
- Agent Team（img-51）：主持人（唯一收敛权）+ 数据分析师 + 开发工程师（读真实源码，可接受/修正/驳回）+ 游戏设计师（立项出 1–3 候选）+ 评审（独立看数、北极星唯一准则）。单次分析最多并发 3 角色；首评独立 Agent 实例，会话隔离。

### FR-5 两类经营决策（沿用 v1.0）

存量改版同基线 A/B（预注册基线/改动/差值区间/样本门槛/期限/证伪条件）；新立项先约束 + 死路审计 → 2–3 候选 → 分析师逐项挑战 → 设计师回应 → 主持人单选 + 淘汰理由 + 重名/同循环拦截 + 上线后绝对指标预期。立项与迭代审批前均为六次角色调用的，审批后去向不同（迭代进生产改版，立项创建新游戏）。

### FR-6 活动入口与经营验证（沿用 v1.0 + 防滥用）

HTTPS 无凭据 URL 校验保留；新增：每空间活动入口数上限（默认 20/游戏）；跳转目标域名 allowlist（空间可配，默认空即禁止外跳）；单玩家跳转频次限流（单 round 只记首次自然完局后首跳，`action_at` 只记自然完局首跳）；防爬（普通爬虫 UA 直接 404 包地址，只暴露宿主 HTML）。

### FR-7 知识、自进化与记忆（沿用 v1.0，对齐 img-56/img-58）

- 未验证不进生效库（`pending → active/unverified/superseded`，只有 `active` 可被引用加权）。
- 召回按游戏 + 玩法 + 置信度；偏好个人默认 + 项目覆盖 + 版本锁 + 最小必要（分析师只取受众/避坑，美术取画风/音频偏好）。
- Agent 节点留痕可审计（角色/模型路由/阶段/系统提示摘要/输入摘要/字节数/图像摘要/调用次数），制作台可打开当时文本与系统提示。
- 可证伪下注（img-56）：提案预注册预测区间 + 引用知识 + 证伪条件 + 反对意见入库 → 人批 → 生产 → AB 发布 → 版本时间线（每日实验配置快照自动推导：版本变更/AB 起止/全量/回滚）→ 到期结算（先对「实际交付了什么」再对照预期取数）→ 三层归因：假设错→修正判断层知识（标已推翻），方法错→退回未验证（度量混杂），执行错→补避坑条目（本次验证作废）。三类修改统一进分层知识库（待评审），再回到下一轮引用。
- 四层记忆（img-58）治理元数据：作用域（单游戏/跨游戏复用）+ 来源证据（结算/会话 ID）+ 证据等级（现象/机制/未验证推断，低等级禁「显著/必然」断言）+ 置信度与状态 + 版本链（可回溯生成时系统状态）。正文只留「结论 + 判断依据」，不存一次性细节与易过期数值。

### FR-8 定时任务与运维（沿用 v1.0 + 公网 SLA）

北京时间 08:00 T+1 整批；30min 巡检；文件锁选主；心跳 + 重试 + 检查点；DB 约束 + 版本号防重放。新增就绪/积压指标与漏批报警（§7 NFR-2/NFR-6）。

### FR-9 多租户、注册与 IAM（v2.1 新增，公网发布的前置，ADR-003）

> 本节是三权分立的总则：**匿名玩家 / 注册玩家 / 开发维护者 / 平台运维四类身份权限正交，任何跨权调用一律拒绝**。现状（`app.py:admin()` 单一共享口令、无 `users` 表）全部为欠账，P6 按本节逐项落地。

- FR-9.1 注册与登录（自然人身份）：
  - 注册：邮箱 + 口令（argon2id/bcrypt 哈希，永存明文为红线；口令 ≥10 位，含字母+数字；同一邮箱全平台唯一）。注册即建 `users(id,email,pass_hash,status,created)`，`status=active` 方可登录；`suspended/deleted` 登录一律 401 且不透露原因。
  - 玩家注册与维护者注册共用同一 `users` 表，**区别只在 `members` 绑定**：无任何空间 `members` 行 = 纯注册玩家；有 `owner/editor/viewer` 行 = 该空间的开发维护者。同一人可同时是 A 空间的 `editor` 与纯玩家（对 B 游戏）。
  - 登录态隔离：维护者 session（制作台 `loop_session`，HttpOnly+Secure+SameSite，12h 滚动）与玩家 session（玩家端 `loop_player_session`，同等 Cookie 属性 + 独立签名盐）**互不可用**：拿玩家 token 调制作台接口一律 401，拿制作台 token 调玩家身份接口一律 401（R-AUTH）。
- FR-9.2 空间与角色：空间有 `owner/editor/viewer`（见 §2）。`owner` 管成员/密钥/预算/删除/冻结；`editor` 做游戏/批方案/触发分析/**处理玩家请求**；`viewer` 只读报表与证据，不可批准、不可触发分析、不可处理请求。
- FR-9.3 鉴权矩阵：见 §9.1（玩家匿名/玩家登录/维护者三档分离；跨空间一律 404；所有人工批准/密钥/成员变更/请求处置双记 `history` + `audit_log`）。
- FR-9.4 兼容期：`STUDIO_ACCESS_KEY` 仅作为**单机/迁移 bootstrap**；公网 `STUDIO_DEPLOYED=1` 且未建空间管理员时，启动失败并提示初始化流程（不允许无口令裸奔，现状 `admin()` 直接放行必须收敛）。bootstrap 创建首个 `owner` 后必须清空该变量，否则 `/readyz` 报 `degraded`。
- FR-9.5 删除与导出：空间可导出（游戏 + 版本包清单 + 报表 CSV），可删（软删 30 天 → 硬删，对象文件随之 GC）；用户可注销（名下空间须先转让 owner 或删除；对局 `player/user_id` 级联匿名化，请求原文随空间删除策略走）。
- FR-9.6 平台运维隔离：PlatformAdmin 只能看跨空间脱敏指标与审计摘要，**不能读游戏源码、GDD 全文、玩家原文、密钥明文**；紧急冻结空间需二次确认 + 写入 `audit_log`（actor=platform_admin）。

### FR-10 外部 API 与开发者体验（v2.1 新增，详见 `API-v1.md`）

- FR-10.1 版本化：`/api/v1/*` 独立于制作台内部路由；语义化版本 + 6 个月弃用期；OpenAPI 即契约，前端 `api-client.js` 与文档同源生成。
- FR-10.2 最小公开面（Phase-1）：建游戏、查版本、开局/事件、读已发布包、读报表摘要；写操作一律 `Idempotency-Key`；分页 `cursor+limit`；错误 `code+message+request_id`。
- FR-10.3 密钥与限流：按 Key 限流（默认 60/min + 突发 120），超限 `429+Retry-After`；密钥可按前缀吊销、可设过期与 IP allowlist。

### FR-11 内容安全与下架（v2.1 新增）

- FR-11.1 游戏标题/简介/GDD/评论走敏感词 + 模型安全复核双检；命中转人工；违规游戏可冻结公共入口（包保留用于申诉举证）。
- FR-11.2 参考图来源可追溯（Commons/本地库/上传三类打标）；上传图限 8MB + 类型白名单 + 二次压缩去 EXIF。
- FR-11.3 玩家反馈评论展示前做 XSS 转义（前端 `esc()` 已有，后端再做一次长度与标签过滤）。

### FR-12 玩家请求上云与维护者审批门（v2.1 新增，本轮核心补齐）

> 原则：**玩家直达 AI 是被禁止的**。玩家侧只产生「请求与证据」，维护者审批后才允许进入 AI 分析；AI 只消费已受理请求与脱敏聚合，不读原始未审工单。现状（`feedback` 表直写、无审批、无身份、无上云收件箱）全部为欠账，P6 按本节落地。

- FR-12.1 提交（上云）：匿名玩家可提交评分+短评（现状 `POST /api/rounds/{token}/feedback` 保留，但语义收敛为「只进证据池，不触发 AI」）；注册玩家可提交带身份工单 `POST /api/v1/player-requests`（`kind: bug/suggestion/balance` + `title/body/game_id/round_ref?`），服务端持久化到 `player_requests`（status=`submitted`），返回回执 ID。提交限流：匿名 IP 10/日，注册用户 20/日；单 body ≤2000 字；XSS 转义 + 敏感词预检（命中转 `moderation_flags`，不直接落库原文）。
- FR-12.2 收件箱（维护者审批）：空间 `editor+` 在制作台「玩家请求」收件箱处理：`triaged → accepted/rejected/merged`，接受/拒绝/合并**必须写理由**（`triage_note`，≥5 字），去重合并需指向主单（`merged_into`）。所有处置写 `audit_log` + `history`。拒绝的请求对玩家可见理由；被合并的请求状态联动主单。
- FR-12.3 进 AI 的唯一合法通道：只有 `status=accepted` 的请求才允许进入下一轮 `frozen_evidence`（以 `request_ids` 数组引用，不贴原文全文；原文仅维护者可看）。`operations.freeze` 必须校验：引用 ID 全为本游戏已受理、未被撤回；否则冻结失败。未受理请求、匿名聚合之外的原文，Agent 上下文**不可见**（`evidence_for` 裁剪规则，R-REQ）。
- FR-12.4 玩家侧查询：注册玩家可查自己工单的状态机进度（`submitted → triaged → accepted/rejected/merged → production → settled`，`production` 指已进提案，`settled` 指实验结算有结论）；匿名玩家凭回执 ID 只可查一次状态（防枚举：回执为 128bit 随机串，失败不区分存在性）。
- FR-12.5 防滥用：同一玩家对同一 bundle 重复提交自动合并（`fingerprint=hash(game+kind+title+body)` 去重 7 天）；刷单（单 IP/单用户突增 5×）触发限流 429 + 人工复核；恶意内容（辱骂/广告/外链）转 `moderation_flags` 并可禁言（`user.status=suspended`，仅封提交权，不封游玩权）。

- FR-11.1 游戏标题/简介/GDD/评论走敏感词 + 模型安全复核双检；命中转人工；违规游戏可冻结公共入口（包保留用于申诉举证）。
- FR-11.2 参考图来源可追溯（Commons/本地库/上传三类打标）；上传图限 8MB + 类型白名单 + 二次压缩去 EXIF。
- FR-11.3 玩家反馈评论展示前做 XSS 转义（前端 `esc()` 已有，后端再做一次长度与标签过滤）。

---

## 6. 非功能需求（NFR，公网版）

| 编号 | 类别 | 要求（Phase-1 单实例目标） |
| --- | --- | --- |
| NFR-1 | 性能/SLO | 开局 P95<800ms（不含模型）；7天报表 P95<2s；已发布包 CDN 命中>90%；QuickJS 0.9s/24MB 保留；模型首评单角色超时 120s + 整体预算（§13） |
| NFR-2 | 可用/可靠 | 单实例月可用 ≥99.5%（维护窗外）；任务至少一次、至多 2 次重试；日报漏批可补跑；RPO≤24h、RTO≤4h（备份三件套可恢复并演练） |
| NFR-3 | 容量上限（显式） | 游戏/空间 ≤50、版本/游戏 ≤200、包 ≤5MB、轮次输入 ≤12000 条（现状值固化）、单日分析任务/空间 ≤20、生图并发 ≤2。超限 429/422 而非拖垮 |
| NFR-4 | 安全 | §11 全项；依赖每月升 + 镜像扫描；密钥只读 env；`.env` 永不打包入库；登录/密钥接口独立严格限流 |
| NFR-5 | 隐私 | PlayerID 匿名；反馈评论可删；空间删除级联匿名化对局玩家标识；日志不记密钥/口令/完整 Token（只记前缀+request_id） |
| NFR-6 | 可观测 | 请求 `X-Request-Id` 全链路；`/healthz`(存活) + `/readyz`(DB+卷+队列) + `/metrics`(特权)；Agent 调用记模型/延迟/Token/费用估算；关键转移写 `history` |
| NFR-7 | 兼容 | Python 3.12 + `requirements-linux.lock`；`linux/x86_64`；桌面 + 390px 视口；Chrome/Safari 近 2 年版本 |
| NFR-8 | 成本护栏 | 单空间月模型/生图预算；单次分析并发 ≤3 角色；输入 160KB 上限裁剪计数；网关失败显式错误（权限/余额/质量分开码） |
| NFR-9 | 合规 | 服务条款+隐私政策版本化；未成年人模式（默认关声音自动播、活动跳转需二次确认，可配）；数据导出机读格式 |

---

## 7. 领域规则（R-REV…R-ART 保留 + 公网 R-AUTH/R-QUOTA）

1. **R-REV**：`serial` 不符 409；非法 stage 转移拒绝（转移表 §8.1）。
2. **R-REF**：`reference_ids` 非空去重且全命中本次选中。
3. **R-BLUEPRINT**：trail grid/size/from/to 连通规则 + 参数边界（`check_curve`）；发布前逐关核对 + 2 Seed 抽检。
4. **R-REPLAY**：自然完局无输入/类型非法/回放三元组不符 → 422（`done/won/score` 必须与服务端同 bundle 同关卡重放一致）。
5. **R-EVIDENCE**：冻结 `level_pack==base==源码` 同版本；零样本显式缺口（禁 V1 样本 + V2 源码错配，`REVIEW-INITIAL` 图 4 反例永不复发）。
6. **R-REVIEW**：全 closed + 全 supported + 全非 open + `validate_decision` 通过才可 `approved`（任一 open/未通过 → `needs_evidence`，重大异议不可被摘要丢弃）。
7. **R-RELEASE**：`validate_release` 全过；parameter 原值=control 实值、目标值=treatment 实值（批准与交付错位永不复发，图 7 反例）；回放一致；资产变更核对。
8. **R-AB**：同人同实验同臂；回访进度三策略显式其一（兼容迁移 / 统一新起点 / 单独分层分析，图 5 进度问题必须预注册其一）。
9. **R-SETTLE**：未到期不结算；窗内干扰降级；样本不足 `delta=null`+未验证；先对交付再对照预期（img-56）。
10. **R-ART**：实体 ID 集一致；新增 `reference` 无环；未计划实体付费前拦截；生图发父实体实际 PNG 并记摘要。
11. **R-AUTH（三权分立）**：特权链路无有效维护者 session/API Key 一律 401；玩家 token 调制作台/运营/管理链路一律 401（反之亦然，会话盐隔离）；跨空间资源一律 404（不泄露存在性）；`viewer` 调写接口一律 403；`editor` 调 owner 专属（成员/密钥/删除/冻结）一律 403；密钥/口令明文永不落库落日志；`STUDIO_DEPLOYED=1` 无初始化直接拒绝启动。
12. **R-QUOTA**：预算/并发/数量任一超限，任务**入队前**拒绝（429/402 语义见 §13），已开始任务记账到空间账本。
13. **R-REQ（玩家请求审批门，新增红线）**：`operations.freeze` 引用的 `request_ids` 必须全为本游戏 `status=accepted` 且未撤回，否则冻结失败；`evidence_for` 裁剪后 Agent 上下文不得含未受理原文；匿名 `feedback` 只进聚合证据、永不单独触发分析任务；任何绕过 `player_requests` 直达 AI 的通道视为 bug。

以上全部要求脱离 FastAPI/Agent 的纯单测（`tests/unit/domain`）。

---

## 8. 状态机与关键流程（沿用 v1.0，补公网分支）

### 8.1 生产状态机（表驱动，ADR-001）

`research → references → interpret → direction → design → plan → build → quality → ready → released`，`revise` 按 `invalidated_artifacts` 回退并 `serial+1`。非法转移一律拒绝：

| from | 允许 to | 条件 |
| --- | --- | --- |
| `research` | `references` | 检索完成（≥1 候选） |
| `references` | `interpret` | 已选 1–4 张参考图 |
| `interpret` | `direction` | 逐图观察 + 规则来源已入库 |
| `direction` | `design` | 人选定玩法方向 |
| `design` | `plan` | 人批 GDD（含资产清单） |
| `plan` | `build` | 关卡 5 章 spec + 资产就绪 |
| `build` | `quality` | 构建产物齐 + QuickJS 验证过 |
| `quality` | `ready` / `plan,build` | 无阻塞项 → `ready`；有阻塞 → 按 `invalidated_artifacts` 回退 |
| `ready` | `released` | 试玩验收（自然完局 + 服务端回放一致）+ 人确认发布 |
| 任意 | `revise` | 人指定返工域，`serial+1` |

### 8.2 运营状态机（PROTOCOL=3）

`analyzing → review → production → running → decide → closed`，`needs_evidence → analyzing`、`failed` 终态；`knowledge: pending → active/unverified/superseded`。
新增：`workspace: active → suspended(欠费/违规) → deleted(软删30天 → 硬删)`；冻结期间公共入口 404、私有包保留；`api_key: active → revoked/expired` 即时失效（内存 + DB 双吊销，最长 60s 生效）。

### 8.2b 玩家请求状态机（FR-12 新增，独立于运营状态机）

`submitted → triaged → accepted/rejected/merged`，`accepted → production(已进提案) → settled(结算有结论)`；`rejected/merged` 为终态（可被主单联动，不可复活，只能重提新单）。

| from | 允许 to | 执行者 | 条件 |
| --- | --- | --- | --- |
| `submitted` | `triaged` | 系统自动 | 去重指纹计算完成，敏感词预检通过 |
| `triaged` | `accepted/rejected/merged` | 空间 editor+ | 必须写 `triage_note`（≥5 字）；`merged` 必须填 `merged_into` |
| `accepted` | `production` | 系统（freeze 引用时） | 被某次 `frozen_evidence.request_ids` 引用 |
| `production` | `settled` | 系统（experiment settle 时） | 引用它的提案结算完成（无论命中/未命中预期） |
| 任意未终态 | `rejected` | 空间 editor+ | 需理由；玩家可见 |

关键约束：运营 `analyzing` 任务只能引用 `accepted` 请求（R-REQ）；`rejected/merged/submitted` 请求被引用时 `freeze` 直接失败，不降级、不跳过。

### 8.3 日批四门禁（img-55，原样落地为需求）

| # | 门禁 | 失败语义 |
| --- | --- | --- |
| ① | 数据整批验收：核心报表任一构建失败 → 中止整批 | 当天所有任务不启动；报警（漏批），可补跑 |
| ② | 产出验收（验真实交付物状态）：立项书是否新建 / 提案是否更新 / 结算清单是否清空 | 未过则同会话续跑（限次）；预算耗尽标失败转人工 |
| ③ | 自动巡检（每 30min）：僵尸（心跳 >180s）/ 漏跑 / 假完成 | 回收续跑，重试 ≤2 次 |
| ④ | 统一交付标准：查重 + 读代码 + 证据引用与交互式一致，产物进待评审队列 | 评审权仍在人手里；自动任务永不直接发布 |

---

## 9. 接口设计

### 9.1 分组与鉴权矩阵

| 分组 | 前缀 | 鉴权 | 限流（默认） |
| --- | --- | --- | --- |
| 玩家匿名公共 | `/api/play/*`、`/api/rounds/*`、`POST /go/*`、`GET /cartridges/v1/*` | 免登（`preview` 除外需 editor+）。**只可玩游戏 + 匿名评分，不可提交工单、不可查进度** | IP 60/min；`open` 按游戏 600/min；`event` 按 round 120/min；`feedback` 按 IP 10/日 |
| 玩家注册 | `/api/v1/player-requests*`（提交工单/查自己工单） | 玩家 session（`loop_player_session`）或玩家 scope API Key。**维护者 session 调此组一律 401** | 注册用户 20/日；查询 60/min；防枚举失败不区分存在性 |
| 制作台 | `/api/games*`、`/api/revisions/*`、偏好/技能/审计 + 玩家请求收件箱（`GET /api/player-requests*` 空间侧） | 维护者 session+RBAC(editor+；收件箱处置需 editor+，只读报表 viewer+ 可看）**玩家 token 调此组一律 401** | 用户 120/min |
| 运营 | `/api/operations*`、`/proposals/*`、`/experiments/*`、`/knowledge/*`、`/memory` | 维护者 session+RBAC(editor+，批准需记录批准人；viewer 只读报表摘要，不可触发分析/批准） | 用户 60/min；`analyze` 按空间 20/日 |
| 资产 | 蓝图/媒体/下载 | 维护者 session+RBAC(viewer+） | 用户 120/min；下载按空间 10GB/日 |
| 空间管理 | `/api/admin/*`（成员/密钥/预算/冻结/导出/删除）+ `/api/auth/*`（注册/登录/登出/轮换） | 注册/登录免登（独立严格限流）；其余 session+RBAC(owner；成员管理 owner，密钥轮换 owner，冻结 owner） | 用户 30/min；登录/注册 10/min/IP，失败延迟 |
| 外部 API | `/api/v1/*`（除 player-requests 外） | API Key + 空间 scope（`games:read/write`、`rounds:write`、`reports:read`、`share`；玩家 scope Key 只能调 rounds+player-requests） | Key 60/min + 突发 120；`Retry-After` |
| 运维 | `/healthz` 公开；`/readyz` 公开轻量；`/metrics` 特权+内网 | — / — / session(owner)+IP allowlist | — |

### 9.2 契约规则（v1.0 保留 + 公网加强）

- 出入参收敛 `api/schemas.py`，Pydantic v2 `extra="forbid"`；字符串 strip；枚举 `Literal`；金额/时间/ID 用 `Annotated` 约束。
- 错误体统一 `{"code": "...", "message": "...", "request_id": "..."}`（兼容旧 `detail`：网关层做一次映射，前端按 `code` 分流 401/404/409/422/429）。
- 写操作幂等：`request_id`/`Idempotency-Key` 或 `(kind,target,stage)` 唯一键；状态变更先验 `serial`/前置态。
- OpenAPI 即契约：`/openapi.json` 生成 `web/api-client.js` 片段 + `docs/API-v1.md`，禁止业务 JS 散写 URL。
- 安全头基线：`X-Content-Type-Options: nosniff`（现状保留）、`Referrer-Policy: same-origin`、`frame-ancestors 'self'`（`frame.html` 独立 CSP 保留且不放宽）、`/api/*: Cache-Control: no-store`、已发布包 `immutable+ETag`。
- MF 宿主契约（img-37/img-38 为接口基线）：`queryGameConfig` 为唯一数据查询通道；生命周期 `onReady/onGameStart/onGameEnd` 单向通知；业务事件只走 `app:event` / `host:event` 双通道，不新增第三通道。
- 玩家请求契约（FR-12）：`POST /api/v1/player-requests`（注册玩家）与 `POST /api/rounds/{token}/feedback`（匿名评分）为玩家侧唯二写入口；`GET /api/v1/player-requests/mine` 只返回本人请求；制作台 `GET /api/player-requests?game=&status=` 只返回本空间请求；`evidence.request_ids` 只引 `accepted` ID，不贴原文；`fingerprint` 去重 7 天幂等。

---

## 10. 数据模型与存储演进

现状 23 张表（`store.py:init`）全部保留并归属空间：`games/revisions/rounds/proposals/experiments/knowledge/campaigns/preferences/...` 加 `workspace_id`（迁移脚本回填默认空间，跨空间查询一律带 `workspace_id=` 前缀条件）。

新增表：`workspaces(id,name,plan,budget,status,created)`、`users(id,email,pass_hash,status,created)`（`status: active/suspended/deleted`）、`members(workspace,user,role)`（`role: owner/editor/viewer`）、`api_keys(id,workspace,prefix,key_hash,scopes,expires,revoked)`（scope 含玩家 `rounds:write` + `player-requests:write/read-own`）、`player_requests(id,game,user_id?,player_fp,kind,title,body,round_ref?,fingerprint,status,triage_note,merged_into,receipt,created,updated)`（`status` 见 §8.2b；`receipt` 为 128bit 回执串哈希；匿名时 `user_id` 为空）、`usage_ledger(id,workspace,kind,qty,meta,at)`（模型 Token/生图次数/存储字节/流量四类）、`audit_log(id,workspace,actor,action,target,detail,at)`（批准/成员/密钥/冻结/删除/**请求处置**）、`moderation_flags(id,game,reason,status,at)`。

Repository（`infra/sqlite_store.py`）：`WorkspaceRepo/MemberRepo/ApiKeyRepo/UsageRepo/AuditRepo` + 原有 Game/Revision/Round/Proposal/Experiment/Knowledge/Job/Preference/Skill/Campaign。**SQL 只允许在此层**。

存储：Phase-1 本地卷三件套（`studio.sqlite3` WAL + `builds/` + `generated-art/`）+ SQLite 在线备份 API；Phase-2（ADR-002）Postgres + S3 兼容对象存储，`cartridge_fs/object_fs` 抽象先行（`read_pack/write_bundle/presign_url/gc_deleted` 四方法）。

---

## 11. 安全设计（公网发布门禁，逐项可验收）

威胁模型（STRIDE 精简）：伪造身份（共享口令/会话固定）→ 按 §9 矩阵收敛；篡改（CSRF/越权读改）→ SameSite+Origin 校验（现状中间件保留）+ 跨空间 404 + `serial` 锁；抵赖 → `audit_log`+`history` 双记；信息泄露（密钥/他空间数据/目录遍历）→ 密钥哈希化、错误信息脱敏、静态目录白名单（`WEB/assets` 外一律 404，现状 `/.env` 已 404 需补单测常态化）；DoS（大量的 open/event/分析/生图）→ §9 限流 + §13 并发/预算；提升权限（XSS 偷 session、非法 frame 嵌套）→ 全站转义 + CSP + `sandbox` 不放宽。

落地清单：口令 argon2id；session 滚动续期 + 登出即吊销；API Key 只存哈希；登录失败延迟 + IP 限流；管理操作二次确认（删除/冻结/全量）；上传白名单 + 大小 + 去 EXIF；QuickJS 限时限内存 + 无 DOM/无 import（现状 `verify_game` 语义保留）；依赖 `pip-audit` + 镜像 Trivy 扫描进 CI；备份加密（卷加密或 age 加密，二选一落地）。

---

## 12. 部署、环境与可观测

环境矩阵（`config/settings.py` 启动校验，缺必填直接拒绝启动）：

| 变量 | 本地 | ModelScope/公网 | 说明 |
| --- | --- | --- | --- |
| `STUDIO_DEPLOYED` | 0 | 1 | 为 1 时强制走公网基线（鉴权+限流+安全头全开） |
| `STUDIO_DATA_DIR` | `data/` | `/mnt/workspace/loop-atelier` | 三件套根目录（`studio.sqlite3` + `builds/` + `generated-art/`） |
| `STUDIO_ACCESS_KEY` | 可空 | 仅 bootstrap 用，建 owner 后可清空 | 不再是日常登录方式 |
| `ZAI_*_TOKEN` / `ZAI_BASE_URL/WIRE_API/MODEL` | 按需 | 至少一组 + 预算告警 | 轮换不重启（SIGHUP 或管理接口热加载，二选一） |
| `STUDIO_ART_*` | 可空（本地绘制） | 按需，独立预算 | 权限/余额/质量失败分开码 |
| `DATABASE_URL` / `OBJECT_STORE_*` | 空（SQLite/本地盘） | Phase-2 才用 | 为空即 Phase-1 模式 |
| `RATE_LIMIT_*` / `BUDGET_*` | 默认 | 按空间可配 | 见 §13 |

部署：`Dockerfile` 保持 `python:3.12-slim` + lockfile + `workers=1`（Phase-1 单实例是特性不是缺陷：简化一致性，扩容走 Phase-2 ADR）；反代（Caddy/Nginx/平台网关）负责 TLS 与 `/cartridges/v1/*` 边缘缓存（`deploy/Caddyfile` 已落地，ECS 方案见 `RUNBOOK.md`）；`package_studio.py` 清单随目录同步，SBOM 一并进包（`sbom.json` 可由 `pip freeze` 生成，Phase-1 先做到可追溯）。

可观测：`X-Request-Id`（无则生成）进日志 + MDC；JSON 结构化日志（`request_id/workspace/game/rev/actor/cost_ms`）；`/readyz` 检查 DB 可写 + 卷剩余>10% + 队列最老等待<30min；`/metrics` 暴露请求延迟直方图、任务积压、网关错误率、预算消耗；Agent 调用记 `agent_runs` + 费用估算进 `usage_ledger`。报警：漏批、僵尸任务>3、就绪失败、预算 80%/100%、网关 5xx 激增。

备份恢复（一页纸）：停写 → `sqlite3 .backup` → 快照卷 → 校验三件套大小与 `manifest` 抽查 → 异机 `readyz` 通过。RPO≤24h（每日）+ RTO≤4h；每季度演练一次并留记录。ECS 落地脚本见 `deploy/backup.sh` / `deploy/restore.sh`。

---

## 13. 配额、预算与费用护栏（模型很贵，先算账）

记账点：文本/多模态调用（Token/次）、生图（次/图）、存储（包+原图字节）、流量（包下载字节）。入队前检查空间预算，超限拒绝码：`QUOTA_EXCEEDED`(429) 配额、`BUDGET_EXCEEDED`(402) 预算（前端引导提额，Phase-1 显示联系管理员）。

默认配额（Phase-1，可按空间调整）：分析 20/日、并发分析 1/空间、生图并发 2/实例、包 5MB、入口 20/游戏、日下载 10GB/空间。费用归因：每次分析/构建把 `usage_ledger` 行 ID 写入 `proposal.evidence.cost_ref`，结算时可查“这次迭代花了多少 Token/几张图”。

---

## 14. 内容安全与合规

用户内容（标题/简介/GDD/评论/上传图）默认**非公开**，仅同空间可见；公开发布（玩家链接/包缓存）需空间 `share` scope + 通过 moderation（自动+抽查）；违规三级：限流 → 冻结入口 → 删空间（逐级留证）。隐私：政策与条款版本化存档；导出/删除 SLA 30 天；日志脱敏抽查进回归。

---

## 15. 目标目录结构（v2.2，公网增补标 ★）

```text
app.py                    # 组装+中间件+探针，不含业务
api/ deps.py schemas.py studio.py player.py ops.py assets.py admin.py★ public_v1.py★ auth.py★
services/ production gameplay operations review experiment knowledge preference batch
  workspace.py★ billing.py★ moderation.py★ requests.py★(玩家请求收件箱)
domain/ revision_machine evidence deliberation_protocol acceptance metrics settlement
  level_rules art_policy ab_assignment quotas.py★ moderation_policy.py★ request_policy.py★(R-REQ)
infra/ sqlite_store(Repository) cartridge_fs object_fs★ quickjs_runtime agent_gateway
  art_gateway research_gateway skill_store job_queue rate_limit.py★ audit.py★ session.py★
config/ settings.py  worker.py(调度器)  studio/engine/(ABI冻结)  studio/skills/(发版固定)
studio/web/ modules/* + api-client.js(OpenAPI生成)
tests/ unit/domain(全R单测) unit/infra integration(按链路拆) fixtures/agent_script.py
  security★(越权/限流/鉴权矩阵) load★(k6/locust 脚本，非CI必跑) backup★(恢复演练脚本)
docs/ SRS.md(本文件) API-v1.md★ ADR/ RUNBOOK.md★(一页恢复+报警处理)
deploy/ Caddyfile backup.sh restore.sh .env.ecs.example★
```

---

## 16. 代码规范（v1.0 保留 + 公网三条）

1. 分层禁令（CI 卡）：`domain` 无 `sqlite3/fastapi/httpx/agentscope/quickjs/os.getenv`；`api` 无 SQL/`quickjs`；`services` 无 SQL 字符串；`auth/配额` 只走 `deps`+`services/workspace|billing`。
2. 类型+Pydantic（`extra="forbid"`）；DomainError→Problem 映射（422/409/404/401/429/402/502，350 字内可读原因）。
3. 幂等+并发（`request_id`/`Idempotency-Key`，`serial` 锁，任务 `attempts≤2`、心跳 15s、僵尸 180s）。
4. 日志审计（禁 `print`；管理/批准/密钥/冻结双记 `history+audit_log`；密钥/Token 只记前缀）。
5. 前端（`api-client.js` 唯一出口；`esc()` 双层转义；409 提示刷新、422 高亮、429 读 `Retry-After`、402 引导提额）。
6. 测试（R 全单测；Repository 临时库；集成复用 fixture；**security 矩阵必跑**：无鉴权调特权 401、跨空间 404、限流 429、越权改 serial 409）。
7. 打包（清单同步新目录；`.env/.venv/data/*.sqlite3/__pycache__` 永不进包；image SBOM 可追溯）。
8. ★ 密钥与配置：新增 env 必须进 §12 矩阵 + `.env.example` + 启动校验三处同步，否则 CI 失败。
9. ★ 迁移脚本：凡加表/加列必须带 `migrate_*.sql` + 回滚说明 + 回填默认空间，禁止手改线上库。
10. ★ 费用：凡新增模型/生图调用必须先记 `usage_ledger` 预算检查，否则 review 打回。

---

## 17. 迁移路线（P0→P7，小步快走，每步回归绿）

- **P0 本文档入库**：`docs/SRS.md v2.1` + `docs/ADR/` 首批（状态机表驱动、Repository 收敛 SQL、单实例 Phase-1、Postgres-Phase-2 预留）。
- **P1 搭骨架**：建 `api/services/domain/infra/config` + 搬 `schemas.py`/`deps.py`；`app.py` 只留组装+探针。门禁：回归绿。
- **P2 收敛数据访问**：`store.py`→`infra/sqlite_store.py` 薄 Repository；裸 SQL 调用点逐个替换；加 `workspace_id` 列与回填脚本（空跑）。
- **P3 抽领域**：`cartridge` 规则/`acceptance`/评审契约/报表结算纯函数→`domain/`，补 `unit/domain`（R-REV…R-QUOTA）。
- **P4 拆服务与路由**：按 §9 分文件；`worker` 瘦身调度器；`review/batch` 服务成形。
- **P5 前端与打包**：拆 `studio.js`+`api-client.js`；`package_studio.py`+Dockerfile 同步；390px 回归。
- **P6 公网加固（本版新增 + v2.2 补齐审批门）**：IAM（注册/空间/密钥/RBAC，维护者与玩家 session 独立盐）→ 玩家请求审批门（`player_requests` + §8.2b + R-REQ，与 IAM 同步上线、不可分离）→ 限流 → 预算记账 → `/readyz`+`/metrics` → 备份脚本+恢复演练 → `RUNBOOK`。门禁：security 矩阵全绿（含 R-REQ：未受理引用 freeze 失败、玩家 token 越权 401、viewer 写 403）+演练记录。
- **P7 外部 API 与规模预案**：`/api/v1` + `API-v1.md` + 示例空间；Postgres/S3 抽象（`object_fs`+`DATABASE_URL` 开关，默认仍 SQLite）；k6 基线（开局/事件/报表三场景）。
- 全程门禁：`ruff` + `unittest` 全绿 + 单 PR<500 行 + 新 env 三处同步 + 新表带迁移脚本。

---

## 18. 验收标准（DoD）

1. 31 项回归全绿（含 4 原反例）+ 新增 security 矩阵（401/403/404/409/422/429 各至少 1 例，另含 R-REQ 专案：引用 `submitted/rejected` 请求 freeze 必须失败、匿名 feedback 永不建 analysis 任务）。
2. `ruff` 零新增告警；`domain` 无违禁 import；`api/services` 无裸 SQL（抽查脚本过）。
3. 体积：`app.py`<120 行；单路由<300 行；单 service<500 行。
4. 公网检查：`STUDIO_DEPLOYED=1` 无初始化直接启动失败；`/healthz` 200、`/readyz` 含 DB/卷/队列三项；`/metrics` 需特权；`/.env` 404；他人空间 404；限流 429 带 `Retry-After`；玩家 token 调制作台 401、维护者 token 调玩家身份接口 401、viewer 写 403、editor 调 owner 专属 403。
5. 恢复演练：用备份三件套异机恢复，抽查包 `manifest` + 一局回放重算通过，留记录。
6. 打包：`dist/loop-atelier-modelscope.zip` 解压启动，`/healthz` 200，`0.0.0.0:7860`，SBOM 可追溯。

---

## 19. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 拆分漂移 | 只搬不改逻辑；31 项回归为唯一行为基线；SQL/`serial` 逐行 diff |
| skill 摘要断裂 | `digest/pin/bind_prompt` 原样保留；先迁目录后动逻辑 |
| 前端契约漂移 | 先冻 OpenAPI 再写 `api-client.js`；旧 `studio.js` 留 `.legacy` 对照 |
| SQLite 公网撑不住 | Phase-1 显式上限+预算+单实例；Phase-2 Postgres/S3 只换 infra（ADR-002） |
| 密钥/费用失控 | 入队前预算检查+记账；密钥哈希化+可吊销；网关错误分码不透支 |
| 内容/合规暴雷 | 默认非公开+发布前 moderation；冻结入口保留举证包；删除 SLA |

---

## 附A：环境变量矩阵（新增必同步 `.env.example`+§12+启动校验）

`STUDIO_DEPLOYED`、`STUDIO_DATA_DIR`、`STUDIO_ACCESS_KEY`(bootstrap)、`ZAI_BASE_URL/WIRE_API/MODEL`、`ZAI_1/2/EXTRA_TOKEN`、`STUDIO_ART_BASE_URL/RESPONSE_MODEL/IMAGE_MODEL/API_KEY`、`DATABASE_URL`(Phase-2)、`OBJECT_STORE_*(Phase-2)`、`RATE_LIMIT_*`、`BUDGET_*`、`LOG_LEVEL`。

## 附B：现状快照（v2.2 基线行数）

`app.py`(1096) · `operations.py`(1149) · `production.py`(790) · `agents.py`(576) · `cartridge.py`(459) · `deliberation.py`(403) · `research.py`(264) · `image_service.py`(257) · `worker.py`(214) · `context.py`(214) · `acceptance.py`(179) · `skillbook.py`(140) · `artwork.py`(103) · `settings.py`(53) · `studio.js`(1708) · `test_studio.py`(1384)。

## 附C：原图→需求追溯表（v2.1 新增，本次深化的主线）

| 原图 | 设计语义 | 落点 |
| --- | --- | --- |
| img-06 L1–L5 | 五层 + 三原则（判断执行分离/硬约束进代码/可证伪下注） | §4.1 绑定表 + §7 R 全系 + §8.3 四门禁 |
| img-14 Producer+6Agent | 制作人统一调度、全链路产物 | §5 FR-1.6 输入输出契约表 |
| img-15 四决策 | 统一规划/设计审核确认/上下文串联/HITL | §5 FR-1.3 门禁链 + §4.1 三原则 |
| img-32 双模式 | runtime 现场生成 vs prefab 离线预制 | §5 FR-3 双模式 + MF 契约 |
| img-37/img-38 MF 协议 | queryGameConfig + 生命周期 + 双向事件 | §5 FR-3 + §9.2 不新增第三通道 |
| img-43 三层容器 | 调度/容器服务/AI Agent + 固化/可变壳 | §5 FR-3 容器映射 + Phase-2 接口不变 |
| img-51 专家团 | 主持人唯一收敛 + 四专家 + 评审 | §5 FR-4 角色表 + 并发≤3 |
| img-55 日批 | 08:00 整批 + 四门禁 + 30min 巡检 | §5 FR-4/FR-8 + §8.3 门禁表 |
| img-56 可证伪 | 预注册→结算→三层归因 | §5 FR-7 + §7 R-SETTLE |
| img-58 四层记忆 | 核心/知识/历史/会话 + 治理元数据 | §5 FR-7 + §2 术语 |

