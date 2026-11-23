# ADR-002：Phase-1 单实例 SQLite 硬化，Phase-2 只换 infra（Single SQLite Hardened, Postgres Later）

- 状态：已接受（现状即单实例，SRS §4.2/§6 NFR-3/§10/§17 P7 预留演进；本 ADR 为长期有效决策）
- 日期：2026-11-23 ｜ 关联：SRS §4.2/§10/§12，`ARCHITECTURE.md §1/§5`，`RUNBOOK.md §3`
- 原图依据：`original/assets/img-06.png`（L4 工程基座「让 Agent 只写差异化逻辑」——基座可替换、契约先行）、`img-43.png`（三层容器：调度/容器服务/AI Agent 分层，存储抽象在容器服务层）

## 背景

当前部署是单进程 FastAPI + 同进程 `worker.serve()` + SQLite WAL + 文件锁选主。公网化最紧缺的不是「换数据库」，而是 IAM/限流/预算/可观测/备份（ADR-003）。若先换库：引入 Postgres/S3 运维复杂度，却不解决越权与费用失控；还会以「换库」为借口改业务语义，导致 31 项回归漂移。

## 决策

1. Phase-1 保持单实例并设**显式硬上限**（SRS §6 NFR-3）：游戏/空间 ≤50、版本/游戏 ≤200、包 ≤5MB、轮次输入 ≤12000 条、单日分析/空间 ≤20、生图并发 ≤2。超限 429/422 而非拖垮；上限进 `/readyz` 与 `/metrics` 可观测。
2. 并发模型冻结：`workers=1`（Uvicorn 单 worker，SQLite WAL 完整性 + `worker.lock` flock 选主）；所有 SQLite 写经 `store.py:db()` 串行；任务 `attempts≤2`、心跳 15s、僵尸 180s 回收。
3. Phase-2 切 Postgres + S3 兼容对象存储时**只替换** `infra/sqlite_store` 与 `infra/cartridge_fs|object_fs`（四方法契约先行：`read_pack/write_bundle/presign_url/gc_deleted`），`domain/services` 契约与 SQL 语义不变。
4. 备份 = 三件套同版本（`studio.sqlite3` WAL + `builds/` + `generated-art/`），SQLite 在线 `.backup` API 零停机快照（`deploy/backup.sh` 已落地）；单取其一视为无效恢复。

## 后果

- `services/domain` 禁止直连 SQLite 或拼接 SQL 字符串；新增存储访问必须走 Repository，否则 CI 打回（`ruff` 自定义规则 + `grep` 抽查脚本）。
- 新增表/列必须带 `migrate_*.sql` + 回滚说明 + 回填默认空间（`workspace_id` 回填脚本空跑先行，P2），禁止手改线上库。
- Phase-2 前禁止以「换库」为由改业务语义；Phase-2 开关只有 `DATABASE_URL` / `OBJECT_STORE_*`，为空即 Phase-1 模式（SRS §12 矩阵）。
- 容量告警线：卷剩余 <20% 警告、<10% 就绪失败；队列最老等待 >30min 就绪失败；僵尸任务 >3 报警（`RUNBOOK.md §2/§4`）。

## 生产落地细节

- WAL 模式 + `synchronous=NORMAL` + `busy_timeout=5000ms`；备份走 `sqlite3.backup` 而非文件拷贝（防 WAL 撕裂）。
- 对象存储抽象先行（P7）：`cartridge_fs` 本地实现与 `object_fs` S3 实现共用同一四方法接口；`presign_url` 过期 ≤15min；`gc_deleted` 只删软删 30 天到期对象。
- 演进门禁：Phase-2 启动前必须先通过 P6（security 矩阵全绿 + 恢复演练记录），否则不切库。
