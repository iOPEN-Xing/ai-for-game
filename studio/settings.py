import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
WEB = ROOT / "studio/web"
ENGINE = ROOT / "studio/engine"
ZONE = ZoneInfo("Asia/Shanghai")
METRICS = {
    "win_rate": "关卡通关率",
    "rounds_per_player": "人均开局数",
    "seconds_per_player": "人均游玩秒数",
    "action_rate": "活动入口点击率",
    "d1_rate": "首玩玩家次日留存率",
}
STAGES = {
    "research": "玩法调研",
    "references": "选择参考图",
    "interpret": "图像与规则分析",
    "direction": "方向选择",
    "design": "方案设计",
    "plan": "方案审核",
    "build": "游戏构建",
    "quality": "试玩验收",
    "ready": "等待发布",
    "superseded": "旧草稿",
    "released": "已发布",
}
PROVIDERS = (
    ("zai_1", "ZAI_1_TOKEN"),
    ("zai_2", "ZAI_2_TOKEN"),
    ("zai_extra", "ZAI_EXTRA_TOKEN"),
)
FAMILIES = {
    "pulse": "点触采集",
    "trail": "路径解谜",
    "drift": "轨道接力",
    "custom": "自定义机制",
}
BASE_RULES = (
    "人工确认方向、方案、质量和发布。运营只提案。仅引用有来源的数据，优先北极星指标。"
)


def data_dir():
    return Path(os.environ.get("STUDIO_DATA_DIR", ROOT / "data")).resolve()


def chat_model():
    return os.getenv("ZAI_MODEL", "glm-5.4")


def deployed() -> bool:
    return os.getenv("STUDIO_DEPLOYED") == "1"


def public_origin() -> str:
    value = os.getenv("STUDIO_PUBLIC_URL", "").strip().rstrip("/")
    if not value:
        return ""
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path
        or url.query
        or url.fragment
    ):
        raise RuntimeError("STUDIO_PUBLIC_URL 须为玩家站点的 HTTPS 根地址")
    return value


def validate_runtime() -> None:
    if os.getenv("STUDIO_DEPLOYED", "0") not in {"0", "1"}:
        raise RuntimeError("STUDIO_DEPLOYED 须为 0 或 1")
    public_origin()
    if deployed() and not os.getenv("STUDIO_ACCESS_KEY", "").strip():
        raise RuntimeError("公网运行须在服务器环境中设置 STUDIO_ACCESS_KEY")
    if os.getenv("ZAI_WIRE_API", "responses") != "responses":
        raise RuntimeError("ZAI_WIRE_API 必须使用 responses")
