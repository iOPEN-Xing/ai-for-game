import os
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
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
    value = os.environ.get("STUDIO_DATA_DIR")
    if value is not None and not value.strip():
        raise RuntimeError("STUDIO_DATA_DIR 需要有效目录")
    return Path(value or ROOT / "data").resolve()


def load_environment():
    """Called by the application entry point. Tools and tests opt in to local secrets."""
    load_dotenv(ROOT / ".env", override=False)


def _name(variable, default):
    value = os.getenv(variable, default).strip()
    if not value or any(c.isspace() for c in value):
        raise RuntimeError(variable + " 需要非空且不含空白的模型名称")
    return value


def _endpoint(variable, default):
    value = os.getenv(variable, default).strip().rstrip("/")
    try:
        url = urlsplit(value)
        host = url.hostname
        _ = url.port
        try:
            loopback = ip_address(host or "").is_loopback
        except ValueError:
            loopback = host == "localhost"
        if (
            not host
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or any(c.isspace() for c in value)
            or not (url.scheme == "https" or (url.scheme == "http" and loopback))
        ):
            raise ValueError
    except ValueError:
        raise RuntimeError(
            variable + " 需要不含凭据的 HTTPS 接口地址，本机回环可使用 HTTP"
        ) from None
    return value


def chat_model():
    return _name("ZAI_MODEL", "glm-5.4")


@dataclass(frozen=True)
class ChatSettings:
    model: str
    base_url: str
    providers: tuple[tuple[str, str], ...] = field(repr=False)


def chat_settings():
    if os.getenv("ZAI_WIRE_API", "responses") != "responses":
        raise RuntimeError("ZAI_WIRE_API 必须使用 responses")
    providers = tuple(
        (name, token)
        for name, env in PROVIDERS
        if (token := os.getenv(env, "").strip())
    )
    return ChatSettings(
        chat_model(), _endpoint("ZAI_BASE_URL", "https://api.z.ai/api/v1"), providers
    )


@dataclass(frozen=True)
class ArtSettings:
    mode: str
    base_url: str
    response_model: str
    image_model: str
    api_key: str = field(repr=False)


def art_settings():
    key = os.getenv("STUDIO_ART_API_KEY", "").strip()
    mode = os.getenv("STUDIO_ART_MODE", "auto")
    if mode not in {"auto", "responses", "local"}:
        raise RuntimeError("STUDIO_ART_MODE 须为 auto、responses 或 local")
    if mode == "auto":
        mode = "responses" if key else "local"
    if mode == "responses" and not key:
        raise RuntimeError("Responses 美术模式需要 STUDIO_ART_API_KEY")
    model = _name("STUDIO_ART_RESPONSE_MODEL", "gpt-image-2")
    return ArtSettings(
        mode,
        _endpoint("STUDIO_ART_BASE_URL", "https://www.maitokens.top/v1"),
        model,
        _name("STUDIO_ART_IMAGE_MODEL", model),
        key,
    )


def research_online():
    value = os.getenv("STUDIO_RESEARCH_ONLINE", "1")
    if value not in {"0", "1"}:
        raise RuntimeError("STUDIO_RESEARCH_ONLINE 须为 0 或 1")
    return value == "1"


def team_key():
    return os.getenv("STUDIO_ACCESS_KEY", "")


def deployed() -> bool:
    return os.getenv("STUDIO_DEPLOYED") == "1"


def public_origin() -> str:
    value = os.getenv("STUDIO_PUBLIC_URL", "").strip().rstrip("/")
    if not value:
        return ""
    _endpoint("STUDIO_PUBLIC_URL", "")
    url = urlsplit(value)
    if url.scheme != "https" or url.path:
        raise RuntimeError("STUDIO_PUBLIC_URL 须为玩家站点的 HTTPS 根地址")
    return value


def validate_runtime() -> None:
    if os.getenv("STUDIO_DEPLOYED", "0") not in {"0", "1"}:
        raise RuntimeError("STUDIO_DEPLOYED 须为 0 或 1")
    data_dir()
    public_origin()
    if deployed() and not team_key().strip():
        raise RuntimeError("公网运行须在服务器环境中设置 STUDIO_ACCESS_KEY")
    chat_settings()
    art_settings()
    research_online()


def studio_day_start(timestamp: int) -> int:
    """Start of the operational calendar day, Asia/Shanghai."""
    return (timestamp + 8 * 3600) // 86400 * 86400 - 8 * 3600
