# ADR-003：公网 IAM、注册与玩家审批门先行于功能扩张（IAM, Registration & Approval Gate Before Features）

本文适用于外部团队自助制作及注册工单。阿里云单制作室的公开试玩范围见 [ADR-004](ADR-004-private-studio.md)。

- 状态：已接受（SRS v2.2 §9–§13 门禁 + FR-12/R-REQ/§8.2b，现状未落地即为欠账；本 ADR 冻结公网发布顺序）
- 日期：2026-11-23 ｜ 关联：SRS §9/§11/§13/§17 P6–P7，`API-v1.md §3⑦⑧`，`RUNBOOK.md §1/§4/§5`
- 原图依据：`original/assets/img-06.png`（底部三原则：硬约束进代码；人只做北极星+审核）、`img-55.jpg`（门禁①整批中止：错误数据比不跑更危险——同理，无 IAM 与审批门的公网比不上线更危险）

## 背景

现状只有一个共享制作台口令（`STUDIO_ACCESS_KEY`），无空间、无成员角色、无 API Key、无预算记账、无用户注册、无玩家请求审批：玩家 `feedback` 直写库、无身份、无上云收件箱，任何请求都可能被直接读入 AI 上下文。公网发布前若先加玩法/模型能力：费用不可预期（模型+生图按 Token/张计费）、越权不可追溯（跨空间读改只差一个 ID）、密钥泄漏不可吊销、**玩家直达 AI（垃圾/重复/恶意输入进分析烧预算、污染证据）**。这是上线前必须封堵的四类风险，优先级高于一切新功能。

## 决策

公网发布顺序冻结为六步（SRS §17 P6–P7），不可跳步：

1. **IAM 与注册**（注册/空间/密钥/RBAC + `audit_log`）：`users/members/workspaces/api_keys` 四表 + argon2id 口令 + `lak_` 密钥哈希化；同一邮箱全平台唯一，无空间绑定即纯注册玩家；维护者 session（`loop_session`）与玩家 session（`loop_player_session`）独立签名盐、互不可用；跨空间一律 404；所有批准/成员/密钥/冻结/**请求处置**双记 `history` + `audit_log`。
1b. **玩家请求审批门**（FR-12 + R-REQ，不可与 IAM 分离上线）：`player_requests` 表 + `§8.2b` 状态机（`submitted → triaged → accepted/rejected/merged → production → settled`）；匿名 `feedback` 只进聚合证据、永不单独触发分析；`freeze` 引用非 `accepted` 请求直接失败；`evidence_for` 裁剪后 Agent 上下文不得含未受理原文。没有这道门，IAM 上线了玩家仍可直达 AI，预算与证据照样被污染。
2. **限流**（§9 矩阵 + §13 并发）：玩家链路 IP/游戏/round 三级；制作/运营按用户；外部 API 按 Key（60/min + 突发 120，`Retry-After`）；模型/生图两条独立并发信号量。
3. **预算记账**（`usage_ledger` 四类：Token/图/字节/流量）：入队前检查，超限 429 配额 / 402 预算；每次分析/构建把 ledger 行 ID 写入 `proposal.evidence.cost_ref`（费用可归因到单次迭代）。
4. **可观测**（`/readyz` + `/metrics`）：DB 可写 + 卷剩余 + 队列深度三项就绪；延迟直方图/积压/网关错误率/预算消耗四类指标；`X-Request-Id` 全链路。
5. **备份恢复演练**（三件套 + 异机 `readyz` + 回放重算）：RPO ≤24h、RTO ≤4h，每季度演练留记录（SRS §18 DoD 第 5 条）。
6. **外部 API**（`/api/v1` 版本化 + OpenAPI 即契约）：前五步全绿后才开放外部写入面。

`STUDIO_ACCESS_KEY` 仅作单机/bootstrap；公网 `STUDIO_DEPLOYED=1` 且未初始化空间管理员时**启动失败**并提示初始化流程（不允许无口令裸奔）。

## 后果

- 凡新增模型/生图调用必须先过预算检查并记 `usage_ledger`，否则 review 打回（SRS §16 第 10 条）。
- 密钥只存哈希（`key_hash` + 前缀索引）、可按前缀吊销、可设过期与 IP allowlist；吊销内存 + DB 双通道，最长 60s 全实例生效。
- 管理操作（删除/冻结/全量）二次确认；登录失败延迟 + IP 限流（10/min/IP）；`/.env` 404 常态化单测。
- 玩家请求处置同样二次确认语义：`accepted/rejected/merged` 必须写 `triage_note`（≥5 字），`merged` 必填 `merged_into`；拒绝理由对玩家可见；处置留痕 `audit_log` 至少 180 天，与批准同等保留。
- 该顺序使 L5「硬约束进代码」可 enforcement：无 IAM 时 `/metrics` 与 `audit_log` 无意义，备份恢复也无权属语义；无审批门时 `freeze` 的 `request_ids` 无合法来源，`evidence_for` 裁剪无从谈起。

## 生产落地细节

- Session：维护者（HttpOnly + Secure + SameSite，12h 滚动续期，登出即吊销）与玩家（同等 Cookie 属性、独立签名盐）**互不可用**，拿玩家 token 调制作台/运营/管理链路一律 401，反之亦然；长期 Key 与短期 Session 权限正交（Key 走空间 scope，Session 走成员 role）。
- 错误语义：无凭证调特权 401、玩家凭证越权调制作台 401、跨空间 404（不泄露存在性）、`viewer` 写操作 403（`FORBIDDEN`）、`serial` 过期 409、回放不一致 422、配额 429（`QUOTA_EXCEEDED`）、预算 402（`BUDGET_EXCEEDED`），前端按 `code` 分流。
- 审计保留期：`audit_log` 至少 180 天不可删（软删空间仍保留审计行，硬删时导出归档）。
