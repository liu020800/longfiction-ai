"""风格迁移器。

将文本从一种风格迁移到另一种风格。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agents.style_controller import (
    StyleProfile,
    StyleFeatures,
    extract_style_features,
    style_features_to_prompt,
    style_distance,
)
from core.llm_router import call_llm, TaskType

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """迁移结果。"""
    original_text: str
    migrated_text: str
    source_style: str
    target_style: str
    original_features: StyleFeatures
    new_features: StyleFeatures
    style_distance_before: float
    style_distance_after: float


class StyleMigrator:
    """风格迁移器。"""

    def __init__(self, llm_call=None):
        self.llm_call = llm_call or self._default_llm_call

    async def _default_llm_call(self, prompt: str, system: str = "") -> str:
        return await call_llm(TaskType.REWRITE, prompt, system=system, temperature=0.6)

    async def migrate(
        self,
        text: str,
        source_style: StyleProfile,
        target_style: StyleProfile,
        preserve_content: bool = True,
    ) -> MigrationResult:
        """风格迁移。"""
        if not text:
            return MigrationResult(
                original_text="",
                migrated_text="",
                source_style=source_style.name,
                target_style=target_style.name,
                original_features=StyleFeatures(),
                new_features=StyleFeatures(),
                style_distance_before=0.0,
                style_distance_after=0.0,
            )

        original_features = extract_style_features(text)
        distance_before = style_distance(original_features, target_style.features)

        # 构造 prompt
        system = (
            "你是一位资深文学编辑，擅长在保留原文核心叙事和情节的前提下，"
            "将文本改写为指定的风格。"
        )
        source_desc = style_features_to_prompt(source_style)
        target_desc = style_features_to_prompt(target_style)
        content_rule = (
            "严格保留原文的核心事件、人物对白顺序和关键信息，不能改变故事情节。"
            if preserve_content else
            "可以适度调整表达以符合目标风格。"
        )
        prompt = (
            f"请将以下文本从「{source_style.name}」风格迁移到「{target_style.name}」风格。\n\n"
            f"## 源风格指南\n{source_desc}\n\n"
            f"## 目标风格指南\n{target_desc}\n\n"
            f"## 要求\n{content_rule}\n"
            f"重点调整：\n"
            f"- 句式节奏（长短句比例）\n"
            f"- 对话与描写的占比\n"
            f"- 词汇风格（更口语/更书面）\n"
            f"- 修辞手法\n\n"
            f"## 原文\n{text}\n\n"
            f"## 改写后正文\n"
        )

        try:
            migrated = await self.llm_call(prompt, system=system)
        except Exception as e:
            logger.error(f"Style migration failed: {e}")
            migrated = text  # 失败则返回原文

        new_features = extract_style_features(migrated)
        distance_after = style_distance(new_features, target_style.features)

        return MigrationResult(
            original_text=text,
            migrated_text=migrated,
            source_style=source_style.name,
            target_style=target_style.name,
            original_features=original_features,
            new_features=new_features,
            style_distance_before=distance_before,
            style_distance_after=distance_after,
        )

    async def migrate_to_natural(
        self,
        text: str,
        target_style: str = "web_novel",
    ) -> str:
        """将 AI 生成的文本迁移到更自然的风格。"""
        from agents.style_controller import get_style_profile
        target = get_style_profile(target_style)
        if target is None:
            logger.warning(f"Unknown target style: {target_style}")
            return text

        # 构造"去 AI 化"prompt
        prompt = (
            f"请将以下文本改写，使其更自然、更不像 AI 生成。\n\n"
            f"目标风格：{target.description}\n\n"
            f"特别要求：\n"
            f"1. 删除所有'心中涌起'、'瞳孔骤缩'、'嘴角微微上扬'等 AI 套话\n"
            f"2. 用具体动作和细节代替抽象心理描写\n"
            f"3. 长短句交替，避免连续短句或连续长句\n"
            f"4. 对话要有区分度，不同角色说话方式要不同\n"
            f"5. 保留原文所有情节和对白，不能删除任何信息\n\n"
            f"## 原文\n{text}\n\n"
            f"## 改写后正文\n"
        )
        try:
            return await self.llm_call(prompt, system="你是一位文学编辑。")
        except Exception as e:
            logger.error(f"De-AI migration failed: {e}")
            return text
