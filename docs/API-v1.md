# 外部 API v1（目标契约，Phase-1 最小公开面 · v2.2 注册与审批门版）

> 本文记录外部团队接入的目标契约。当前阿里云版本对公众开放已发布游戏和相应的玩家事件。内部 HTTP 契约来自 FastAPI 生成的 OpenAPI。产品范围见 [ADR-004](ADR/ADR-004-private-studio.md)，实际调用链见 [运行架构](ARCHITECTURE.md)。
> 原图依据：`original/assets/img-37/img-38.png`（宿主三通道为玩家面契约基线）、`img-32.png`（双模式包契约）、`img-06.png`（L4/L5 交付物不可变）。

## 1. 版本与兼容

- 基址：`/api/v1/*`，独立于制作台内部路由；语义化版本（SemVer），破坏性变更发新大版本 + **6 个月弃用期**（弃用头 `Deprecation` + `Sunset` + 迁移指南）。
- `OpenAPI` 即契约：`/openapi.json` 为唯一真源，生成 `web/api-client.js` 片段与本文；禁止业务 JS 散写 URL（`studio.js` 直写 URL 在 P5 全部收敛）。
- 错误体统一：`{"code": "...", "message": "...", "request_id": "..."}`；兼容旧 `detail` 由网关层做一次映射。`message` 350 字内可读原因，不泄露内部路径与 SQL。
- 幂等：所有 POST/PUT/PATCH 写操作支持 `Idempotency-Key`（或 `request_id`）；服务端以 `(workspace, kind, target, stage, key)` 去重 24h，重复提交返回首次结果（不重放副作用）。

## 2. 认证与限流

- 认证：`Authorization: Bearer lak_<prefix>_<secret>`（维护者 Key，空间 scope）或玩家 session（`loop_player_session`，独立签名盐）；服务端只存 `key_hash` + 前缀索引；密钥只在创建时出现一次，可按前缀吊销、可设过期与 IP allowlist；吊销 60s 内全实例生效（内存 + DB 双通道）。**两类凭证互不可用**：玩家凭证调制作台/运营/管理链路一律 401，反之亦然（SRS R-AUTH）。
- 鉴权：Key 绑定空间 scope（`games:read/write`、`rounds:write`、`reports:read`、`share`、`player-requests:triage`；玩家 scope Key 只能调 rounds+player-requests）；跨空间资源一律 404（不泄露存在性）；`preview` 包需 `editor+`，已发布包免登；`viewer` 调写接口 403，`editor` 调 owner 专属 403。
- 限流（默认，SRS §9.1）：Key 60/min + 突发 120，超限 `429 + Retry-After`（秒）+ `X-RateLimit-Remaining`；`open` 按游戏 600/min、`event` 按 round 120/min；分析类按空间 20/日（走制作台 session，不开放 v1 写分析）。

## 3. Phase-1 最小公开面（8 组，冻结）

| # | 方法与路径 | 说明 | 入参要点 | 现状对照 |
| --- | --- | --- | --- | --- |
| 1 | `POST /api/v1/games` | 建游戏（归属 Key 空间，`request_id` 幂等，跨空间不互认） | `title, idea, north_star(5选1), boundary` | 现状 `POST /api/games`（`app.py:create`），缺空间归属 → P7 补 |
| 2 | `GET /api/v1/games/:id` | 查版本与阶段（含 `stage/serial/bundle`） | — | 现状 `GET /api/games/{gid}`（`app.py:game`） |
| 3 | `POST /api/v1/rounds/open` | 开局（领取对局记录，返回 `token + bundle_url + seed policy`） | `game_id, campaign?, arm?` | 现状 `POST /api/play/{gid}/open`（`app.py:open_round`） |
| 4 | `POST /api/v1/rounds/:token/event` | 上报事件（自然完局须带输入；服务端同 bundle 同关卡回放，三元组不符 422） | `events[], inputs[], client_ts` | 现状 `POST /api/rounds/{token}/event`（`app.py:event`） |
| 5 | `GET /api/v1/cartridges/:bundle.json` | 读已发布包（`immutable + ETag`，CDN 缓存 1 年） | `If-None-Match` | 现状 `GET /cartridges/v1/{bundle}.json`（`app.py:public_cartridge`） |
| 6 | `GET /api/v1/reports/summary` | 读报表摘要（分页 `cursor+limit`，默认 20、最大 100） | `game_id?, range=7d\|30d\|all, cursor, limit` | 现状 `GET /api/operations`（`app.py:ops`，内部口径，需收敛到摘要） |
| 7 | `POST /api/v1/player-requests` + `GET /api/v1/player-requests/mine` | 注册玩家提交工单（`kind/title/body/game_id/round_ref?`，`fingerprint` 7 天去重）+ 查自己工单状态机进度 | 玩家 session；限流 20/日；`body ≤2000` 字；回执 128bit 防枚举 | 现状缺失（仅 `POST /api/rounds/{token}/feedback` 匿名评分直写 `feedback` 表，无身份、无审批 → P6 按 SRS FR-12 重做为证据池语义） |
| 8 | `POST /api/auth/register` / `login` / `logout` | 邮箱+口令注册登录（argon2id，同一邮箱全平台唯一；`suspended/deleted` 不透露原因）；维护者 session 与玩家 session 独立签名盐、互不可用 | 免登但独立严格限流 10/min/IP + 失败延迟；`STUDIO_DEPLOYED=1` 未初始化直接拒绝启动 | 现状仅 `POST /api/login` 单共享口令（`app.py:login/admin`，无 `users` 表 → P6 替换，`STUDIO_ACCESS_KEY` 降级为 bootstrap） |

不在 Phase-1 的面（明确不开放）：建提案/批提案/触发分析/成员密钥管理（走制作台 session + `/api/admin/*`）；包上传（只读发布包，写包走制作台构建链）；**玩家请求收件箱处置（`GET /api/player-requests?game=&status=` + `accepted/rejected/merged`）只走制作台 editor+，永不进 `/api/v1`**（审批权不出空间）。

## 4. 数据契约要点

- 分页：`{"items": [...], "next_cursor": "...|null"}`；`cursor` 不透明，`limit` 越界 422。
- 时间：RFC3339 UTC；金额分单位整数；ID 用 `Annotated` 约束（`game_…/rev_…/round_…` 前缀 + 26 位 ULID 语义）。
- 包：`manifest.json` 含 `bundle_hash/sha256/file_bytes/game_abi/curve_abi`；客户端缓存键 = `bundle_hash`，`ETag: "<bundle_hash>"`。
- 回放：`event` 自然完局（`done=true`）必须带 `inputs`（空数组 422）；服务端 QuickJS 同 bundle 同关卡重放，`done/won/score` 任一不符 422（R-REPLAY）。

## 5. 错误码（冻结，与 SRS §7 对应）

| 码 | HTTP | 含义 | 触发示例 | 前端动作 |
| --- | --- | --- | --- | --- |
| `UNAUTHENTICATED` | 401 | 未认证 | 特权链路无有效 session/API Key；玩家凭证调制作台（反之亦然） | 跳登录/换 Key |
| `FORBIDDEN` | 403 | 已认证但无权限 | viewer 调写接口、editor 调 owner 专属、匿名玩家调工单接口 | 提示无权限，不重试 |
| `NOT_FOUND` | 404 | 不存在（或跨空间影藏） | 他空间资源、未发布包、他人工单（防枚举不区分存在性） | 不重试 |
| `STALE_SERIAL` | 409 | 状态冲突 | `serial` 过期、非法 stage 转移 | 提示刷新后重试 |
| `UNPROCESSABLE` | 422 | 语义不可执行 | 回放三元组不符、无输入自然完局、包超 5MB、limit 越界 | 高亮字段，不重试 |
| `QUOTA_EXCEEDED` | 429 | 配额超限 + `Retry-After` | 见 SRS §13 默认配额 | 读 `Retry-After` 退避 |
| `BUDGET_EXCEEDED` | 402 | 预算超限 | 空间月预算用尽 | 引导提额/联系管理员 |
| `UPSTREAM_FAILED` | 502 | 网关失败（权限/余额/质量分开码） | Z.AI 5xx / 美术网关失败 | 不透支，留检查点 |

## 6. 实现 checklist（P7，按序验收）

1. 新建 `api/public_v1.py` + `api/deps.py`（API Key + RBAC + 限流依赖）+ `api/schemas.py` 收敛（`extra="forbid"`）。
2. 冻结 OpenAPI 并生成 `web/api-client.js`，旧 `studio.js` 散写 URL 逐个替换（`grep -rn "fetch('/api" studio/web` 清零）。
3. `Idempotency-Key` 去重表 + `serial` 锁 + 三件套只读包链路（`cartridge_fs.read_pack`）。
4. security 矩阵回归必过：无鉴权调特权 401、跨空间 404、越权改 serial 409、回放篡改 422、限流 429（带 `Retry-After`）、预算耗尽 402。
5. k6 基线（开局/事件/报表三场景）+ CDN 命中率 >90% 验证 + SBOM 可追溯。
