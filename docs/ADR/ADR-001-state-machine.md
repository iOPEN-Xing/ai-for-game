# ADR-001：生产与运营状态机表驱动（Production/Operations State Machine as Tables）

- 状态：已接受（现状即如此，SRS §8 冻结语义；本 ADR 为长期有效决策）
- 日期：2026-11-23 ｜ 关联：SRS §7 R-REV/R-REVIEW/R-RELEASE/R-SETTLE，§8.1/§8.2，`ARCHITECTURE.md §4`
- 原图依据：`original/assets/img-06.png`（L1–L5 流转必须可审计）、`img-14/img-15.png`（Producer 统一规划、设计→审核→确认）、`img-55.jpg`（日批四门禁依赖确定性状态）

## 背景

生产（`research → … → released`）与运营（`analyzing → … → closed`）曾散落在条件分支里，返工/退回语义靠人工记忆。`REVIEW-INITIAL.md` 图 4（数据与源码错版：V1 样本配 V2 源码）与图 7（批准与交付错位：批 10 秒、做计分、照样开闸）的根因都是**状态转移无单一可信表**：审批时比对的是「当前线上版本」，而不是「冻结证据绑定的版本」。

## 决策

1. 状态转移只由表驱动：生产 `production.STEPS/NEXT` + 运营 `deliberation.PROTOCOL=3` + `operations` 批次/实验/知识状态，三表为唯一真源。
2. 每次写操作双重校验：`serial` 乐观锁（过期 → 409）+ `stage` 前置条件（非法转移 → 拒绝并返回可读原因，350 字内）。
3. `revise` 不新增状态，只按 `invalidated_artifacts`（策划/美术/关卡/代码四域）回退并 `serial+1`；下游产物按依赖精确失效（`merge_assets` 语义保留）。
4. 运营侧 `needs_evidence → analyzing` 为唯一回流边；`failed` 为终态，不可复活，只能新建任务（防僵尸复活）。

## 后果

- 新增状态必须同步更新状态表 + SRS §8 + 回归用例三处，否则 CI 失败（`tests/unit/domain` 卡 R-REV/R-REVIEW）。
- `api/services` 只消费判定结果（`validate_decision`/`validate_release`），不私自推导下一阶段；前端 409 必须提示刷新，不静默覆盖。
- 该决策使 L2「只分析不执行」/ L3「只执行不分析」分离可 enforcement：分析链写不了 `released`，生产链写不了 `approved`。

## 生产落地细节

- 锁粒度：以 `(revision_id, serial)` 为乐观锁键；`UPDATE … WHERE serial=?` 影响行数为 0 即 409，不做先读后写。
- 审计：每次转移写 `history`（revision 级）+ 关键转移写 `audit_log`（空间级，P6 后）；`request_id` 全链路透传，幂等键 `(kind,target,stage)` 唯一约束防重放。
- 可观测：非法转移计数进 `/metrics`（`invalid_transition_total{from,to}`），激增报警（有人在刷接口或前端版本漂移）。
