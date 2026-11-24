"""Instructions specific to an operations task or deliberation phase."""

TASK_PROMPTS = {
    "iteration": "存量改版。只把当前版本的正式样本归给其源码，其他版本和同类游戏只作对照。"
    "四人独立，再由评审逐条质询责任人。工程师核对源码和实际关卡。主持人的每个 checks 对应明确的改动。"
    "parameter 用 level_pack 当前值和目标值，replay 用 probes 中同一组输入的 observed 值和预测值，asset 用实体 ID。"
    "没有证据就留下 open。low/high 是实验减对照的绝对差。最终评审核对改动、指标和全部争议。",
    "new_game": "新游戏立项。先独立核对目标人群、北极星、同类样本和 dead_ends。约束和口径审计齐备后才设计两三个不同核心循环。"
    "每个候选的 evidence 是 sources 中的一个 ID。分析师质询设计师的候选，设计师答复。主持人选一，将 title 写成所选候选原名，"
    "说明每个落选理由并逐一裁决问题。low/high 是上线后自身指标的绝对预期区间。终审核对 portfolio 重合、死路、样本与口径。",
}
PHASE_PROMPTS = {
    "constraints": "交付开工约束。分析师量化可用分母与人群，评审核对已知死路和口径，工程师明确可实施边界。",
    "independent": "仅依据冻结事实提交独立判断，指出可以行动的原因。",
    "candidates": "依据前置两份审计提交不同候选，为每个写出受众、循环、差异和证据。",
    "challenge": "针对具体观点提出 1–4 个可回答的问题，指定对应责任专家；质询设计候选时须包含 GameDesigner。",
    "reply": "作为被质询人回答你负责的问题，必要时修正原建议。缺少证据时 supported=false。",
    "hold": "对仍缺乏依据的问题只给出简明原因和补证清单。说明负责人具体还要取得哪项数据或代码证据，收齐之前停在此处。",
    "adjudicate": "只裁决当前 question，对照 answer 和可见证据。reason 写明是否调整方案及原因。无法采信、责任人未支持或仍缺数据则 disposition=open。",
    "verify_issue": "独立复核本条质疑、回应、裁决与最终提案。若问题仍在、证据不实或改动无法执行则 closed=false。",
    "decision": "依据 decisions 形成一个可预注册、可执行的方案。citations 只能是生效知识条目 ID，没有填 []。refs 只能是 evidence.sources 中的 ID。迭代检查只选真实存在且在批准范围的一个最小修改。parameter 的 before 取实际关卡字段，after 使用 ABI 允许范围。新立项 title 与 selected 均逐字复制入选候选名称。",
    "final_review": "对主持人的最终提案和每项回复做独立终审。证据不足或提案与可执行检查不一致时 approved=false。新立项须核查已有核心循环，portfolio_check.closest_title 使用目录中的最相似项目原名，空目录填 null，说明玩法差异与重合风险。",
}
