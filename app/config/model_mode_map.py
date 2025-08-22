"""Model -> mode_title 映射配置。

提供可扩展、多对一的映射规则。优先使用精确映射，其次按正则模式顺序匹配。
可以在这里扩展或从外部文件加载覆盖。
"""
from typing import Optional, Iterable, Tuple, List
import re

# 精确匹配字典（优先）
EXACT_MAP = {
    "copilot-chat": "快速响应",
    "gpt-5-chat-latest": "Smart (GPT-5)",
}

# 模式映射：按顺序匹配，支持正则（忽略大小写）
PATTERN_MAP: List[Tuple[str, str]] = [
    (r"(?i)gpt[-_ ]?5|gpt5|smart|", "Smart (GPT-5)"),
    (r"(?i)think|deeper|reasoning|o3|gpt-think", "Think Deeper"),
    (r"(?i)fast|quick|快速|gpt[-_ ]?4o|gpt4o", "快速响应"),
]


def get_mode_title_for_model(model_name: Optional[str]) -> Optional[str]:
    """根据 model 名称返回对应的 mode_title，找不到则返回 None。

    支持精确匹配和模式匹配（按 PATTERN_MAP 顺序）。
    """
    if not model_name:
        return None
    model_name = model_name.strip()

    # 精确匹配首选
    if model_name in EXACT_MAP:
        return EXACT_MAP[model_name]

    # 模式匹配（按顺序）
    for pattern, title in PATTERN_MAP:
        try:
            if re.search(pattern, model_name):
                return title
        except re.error:
            # 忽略坏的正则
            continue

    return None


def register_exact_mapping(model: str, title: str):
    """运行时注册精确映射（覆盖）。"""
    EXACT_MAP[model] = title


def register_pattern_mapping(pattern: str, title: str, at_start: bool = False):
    """运行时注册模式映射；默认追加到末尾，设置 at_start=True 可插在前面以提高优先级。"""
    if at_start:
        PATTERN_MAP.insert(0, (pattern, title))
    else:
        PATTERN_MAP.append((pattern, title))
