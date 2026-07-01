"""全局配置。

API Key 有两种填法（任选其一）：
  1) 设置环境变量 DASHSCOPE_API_KEY（推荐，避免泄露到代码库）。
  2) 直接把下面的 API_KEY 占位符替换成你的 key。

推理问答阶段只能调用 Qwen 系列模型（百炼 / 魔搭），禁用 embedding 模型。
"""

import os
from pathlib import Path

# ------------------------------------------------------------------ #
# API 凭证（先预留，后续自行填入）
# ------------------------------------------------------------------ #
# 优先读环境变量；没有则用占位符。请勿把真实 key 提交到 git。
API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "<在此填入你的_DASHSCOPE_API_KEY>")

# 百炼（DashScope）OpenAI 兼容端点。若用魔搭可改成对应 base_url。
BASE_URL: str = os.getenv(
    "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 评测基准模型（赛题指定 Qwen3.6-plus）。如平台模型 id 不同，在此调整。
MODEL_NAME: str = os.getenv("QWEN_MODEL", "qwen3.6-plus")

# ------------------------------------------------------------------ #
# 路径
# ------------------------------------------------------------------ #
ROOT: Path = Path(__file__).resolve().parent.parent
RAW_DIR: Path = ROOT / "raw"
QUESTIONS_DIR: Path = ROOT / "questions"
PROCESSED_DIR: Path = ROOT / "processed_data"
LOGS_DIR: Path = ROOT / "logs"
OUTPUT_DIR: Path = ROOT  # answer.csv / evidence.json 输出到根目录

# 五个领域标识
DOMAINS = [
    "insurance",
    "regulatory",
    "financial_contracts",
    "financial_reports",
    "research",
]

# ------------------------------------------------------------------ #
# 评测 / 预算参数
# ------------------------------------------------------------------ #
TOKEN_BUDGET: int = 5_000_000          # 评分归一化预算
PER_QUESTION_TOKEN_TARGET: int = 25_000  # 单题软上限（用于监控告警）

# ------------------------------------------------------------------ #
# 推理调用默认参数
# ------------------------------------------------------------------ #
DEFAULT_TEMPERATURE: float = 0.0
DEFAULT_MAX_TOKENS: int = 1024
REQUEST_TIMEOUT: int = 120
MAX_RETRIES: int = 3

# 证据片段送入模型时的单段字符上限（控制 prompt token）
EVIDENCE_CHUNK_MAX_CHARS: int = int(os.getenv("EVIDENCE_CHUNK_MAX_CHARS", "1800"))

# 自洽验证模式：off | selective | all
VERIFY_MODE: str = os.getenv("VERIFY_MODE", "selective")


def api_key_is_placeholder() -> bool:
    """判断 API Key 是否仍是占位符（尚未填入）。"""
    return (not API_KEY) or API_KEY.startswith("<")


for _d in (PROCESSED_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
