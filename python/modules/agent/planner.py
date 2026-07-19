from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from typing import Literal

from .interpret import InterpretResult
from .route_policy import resolve_step_route


@dataclass
class PlanStep:
    id: str
    title: str
    kind: str = "action"
    description: str = ""
    payload: dict[str, Any] | None = None
    depends_on: list[str] = field(default_factory=list)
    condition: StepCondition | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None


@dataclass
class StepCondition:
    source_step_id: str = ""
    mode: str = "continue_if"
    status_in: list[str] = field(default_factory=list)
    status_not_in: list[str] = field(default_factory=list)
    content_contains: list[str] = field(default_factory=list)
    error_contains: list[str] = field(default_factory=list)
    all_of: list["StepCondition"] = field(default_factory=list)
    any_of: list["StepCondition"] = field(default_factory=list)
    none_of: list["StepCondition"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PlanMode = Literal["immediate", "scheduled_once", "scheduled_interval", "mixed"]


@dataclass
class PlanResult:
    goal: str
    mode: PlanMode = "immediate"
    steps: list[PlanStep] = field(default_factory=list)
    delay_seconds: int | None = None
    interval_seconds: int | None = None
    immediate_steps: list[PlanStep] = field(default_factory=list)
    scheduled_steps: list[PlanStep] = field(default_factory=list)


class Planner:
    """最小启发式 Planner。

    当前不调用第二个 LLM，只将目标封装成一个可扩展的步骤列表。
    后续可以替换为真正的多步规划器。
    """

    def plan(self, goal: str, interpret_result: InterpretResult | None = None) -> PlanResult:
        normalized = (goal or "").strip()
        if not normalized:
            return PlanResult(goal="", steps=[])

        delay_match = re.search(r"(\d+)\s*(秒|分钟|分|小时)后", normalized)
        interval_match = re.search(r"每隔\s*(\d+)\s*(秒|分钟|分|小时)", normalized)
        has_immediate_hint = any(token in normalized for token in ["现在", "立刻", "马上", "先"])
        has_tool_hint = bool(interpret_result.tool_hint) if interpret_result is not None else any(token in normalized for token in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件"])

        conditional_match = re.search(r"(.+?)(?:，|,|。|\s)+如果(成功|失败)(?:且([^，,。]*))?(?:的话)?(?:，|,|\s)*(.*)$", normalized)
        if conditional_match:
            primary_prompt = conditional_match.group(1).strip()
            condition_kind = conditional_match.group(2).strip()
            condition_detail = (conditional_match.group(3) or "").strip()
            branch_prompt = conditional_match.group(4).strip()
            condition_filters = self._condition_filters_from_text(condition_detail)

            analysis_step = self._make_step(
                title="Understand conditional goal",
                kind="analysis",
                description=normalized,
            )
            primary_step = self._make_step(
                title="Execute primary branch",
                kind="tool" if self._looks_like_tool_prompt(primary_prompt) else "agent",
                description=primary_prompt,
                payload={"prompt": primary_prompt},
                depends_on=[analysis_step.id],
            )
            else_match = re.search(r"(.+?)(?:，|,|\s)+否则(?:的话)?(?:，|,|\s)*(.*)$", branch_prompt)
            branch_steps: list[PlanStep] = []
            if else_match:
                conditional_prompt = else_match.group(1).strip()
                fallback_prompt = else_match.group(2).strip()
                branch_steps.append(self._make_step(
                    title=f"Execute {'failure' if condition_kind == '失败' else 'success'} branch",
                    kind="tool" if self._looks_like_tool_prompt(conditional_prompt) else "agent",
                    description=conditional_prompt,
                    payload={"prompt": conditional_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="continue_if",
                        status_in=["error", "skipped"] if condition_kind == "失败" else ["ok"],
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
                branch_steps.append(self._make_step(
                    title="Execute else branch",
                    kind="tool" if self._looks_like_tool_prompt(fallback_prompt) else "agent",
                    description=fallback_prompt,
                    payload={"prompt": fallback_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="skip_if",
                        status_in=["error", "skipped"] if condition_kind == "失败" else ["ok"],
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
            else:
                selected_statuses = ["error", "skipped"] if condition_kind == "失败" else ["ok"]
                branch_steps.append(self._make_step(
                    title=f"Execute {'failure' if condition_kind == '失败' else 'success'} branch",
                    kind="tool" if self._looks_like_tool_prompt(branch_prompt) else "agent",
                    description=branch_prompt,
                    payload={"prompt": branch_prompt},
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="continue_if",
                        status_in=selected_statuses,
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
                branch_steps.append(self._make_step(
                    title="Continue without conditional branch",
                    kind="analysis",
                    description="No one-sided conditional branch was selected; continue to final synthesis.",
                    depends_on=[primary_step.id],
                    condition=StepCondition(
                        source_step_id=primary_step.id,
                        mode="skip_if",
                        status_in=selected_statuses,
                        content_contains=condition_filters.get("content_contains", []),
                        error_contains=condition_filters.get("error_contains", []),
                    ),
                ))
            join_step = self._make_step(
                title="Merge conditional branches",
                kind="join",
                description="Merge the branch path that actually ran before final synthesis.",
                depends_on=[step.id for step in branch_steps],
            )
            synthesis_step = self._make_step(
                title="Synthesize conditional result",
                kind="agent",
                description=normalized,
                payload={"prompt": normalized},
                depends_on=[join_step.id],
                condition=StepCondition(
                    source_step_id=join_step.id,
                    mode="continue_if",
                    status_in=["ok"],
                ),
            )

            return PlanResult(
                goal=normalized,
                mode="immediate",
                steps=[analysis_step, primary_step, *branch_steps, join_step, synthesis_step],
                immediate_steps=[primary_step, *branch_steps, join_step, synthesis_step],
            )

        def to_seconds(value: str, unit: str) -> int:
            amount = int(value)
            if unit == "秒":
                return amount
            if unit in {"分钟", "分"}:
                return amount * 60
            if unit == "小时":
                return amount * 3600
            return amount

        if interval_match or (interpret_result is not None and interpret_result.intent == "schedule" and "每隔" in normalized):
            analysis_step = self._make_step(
                title="Interpret scheduled interval request",
                kind="analysis",
                description=normalized,
            )
            interval_seconds = to_seconds(interval_match.group(1), interval_match.group(2)) if interval_match else 60
            scheduled_step = self._make_step(
                title="Create interval schedule",
                kind="schedule",
                description=f"interval={interval_seconds}s",
                payload={"mode": "interval", "interval_seconds": interval_seconds, "prompt": normalized},
                depends_on=[analysis_step.id],
            )
            result = PlanResult(
                goal=normalized,
                mode="scheduled_interval",
                interval_seconds=interval_seconds,
                steps=[
                    analysis_step,
                    scheduled_step,
                ],
                scheduled_steps=[scheduled_step],
            )
            if has_immediate_hint:
                immediate_step = self._make_step(
                    title="Execute immediate request",
                    kind="agent",
                    description=normalized,
                    payload={"prompt": normalized},
                    depends_on=[analysis_step.id],
                )
                result.mode = "mixed"
                result.steps.append(immediate_step)
                result.immediate_steps.append(immediate_step)
            return result

        if delay_match or (interpret_result is not None and interpret_result.intent == "schedule"):
            analysis_step = self._make_step(
                title="Interpret delayed task",
                kind="analysis",
                description=normalized,
            )
            delay_seconds = to_seconds(delay_match.group(1), delay_match.group(2)) if delay_match else 60
            scheduled_step = self._make_step(
                title="Create one-shot schedule",
                kind="schedule",
                description=f"delay={delay_seconds}s",
                payload={"mode": "once", "run_after_seconds": delay_seconds, "prompt": normalized},
                depends_on=[analysis_step.id],
            )
            result = PlanResult(
                goal=normalized,
                mode="scheduled_once",
                delay_seconds=delay_seconds,
                steps=[
                    analysis_step,
                    scheduled_step,
                ],
                scheduled_steps=[scheduled_step],
            )
            if has_immediate_hint:
                immediate_step = self._make_step(
                    title="Execute immediate request",
                    kind="agent",
                    description=normalized,
                    payload={"prompt": normalized},
                    depends_on=[analysis_step.id],
                )
                result.mode = "mixed"
                result.steps.append(immediate_step)
                result.immediate_steps.append(immediate_step)
            return result

        tool_prompts = self._split_tool_prompts(normalized) if has_tool_hint else []
        if len(tool_prompts) > 1:
            analysis_step = self._make_step(
                title="Understand goal",
                kind="analysis",
                description=normalized,
            )
            tool_steps: list[PlanStep] = []
            previous_id = analysis_step.id
            for index, prompt in enumerate(tool_prompts):
                step = self._make_step(
                    title=f"Execute tool step {index + 1}",
                    kind="tool",
                    description=prompt,
                    payload={"prompt": prompt},
                    depends_on=[previous_id],
                )
                tool_steps.append(step)
                previous_id = step.id
            followup_agent_step = self._make_step(
                title="Synthesize final response",
                kind="agent",
                description=normalized,
                payload={"prompt": normalized},
                depends_on=[previous_id],
            )
            return PlanResult(
                goal=normalized,
                mode="immediate",
                steps=[
                    analysis_step,
                    *tool_steps,
                    followup_agent_step,
                ],
                immediate_steps=[*tool_steps, followup_agent_step],
            )

        analysis_step = self._make_step(
            title="Understand goal",
            kind="analysis",
            description=normalized,
        )
        immediate_step = self._make_step(
            title="Execute via agent pipeline",
            kind="tool" if has_tool_hint else "agent",
            description=normalized,
            payload={"prompt": normalized},
            depends_on=[analysis_step.id],
        )
        return PlanResult(
            goal=normalized,
            mode="immediate",
            steps=[
                analysis_step,
                immediate_step,
            ],
            immediate_steps=[immediate_step],
        )

    def _make_step(
        self,
        *,
        title: str,
        kind: str,
        description: str = "",
        payload: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        condition: StepCondition | None = None,
    ) -> PlanStep:
        route = resolve_step_route(kind)

        return PlanStep(
            id=f"step_{abs(hash((title, kind, description, tuple((depends_on or []))))) % 10_000_000}_{len(description)}",
            title=title,
            kind=kind,
            description=description,
            payload=payload,
            depends_on=list(depends_on or []),
            condition=condition,
            owner_agent_id=route.owner_agent_id,
            owner_agent_role=route.owner_agent_role,
            route_reason=route.route_reason,
        )

    def _looks_like_tool_prompt(self, text: str) -> bool:
        return any(keyword in text for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件"]) or bool(re.search(r"https?://\S+", text))

    def _condition_filters_from_text(self, text: str) -> dict[str, list[str]]:
        normalized = (text or "").strip()
        if not normalized:
            return {}

        content_match = re.search(r"(?:输出|结果|内容)包含\s*([^，,。]+)", normalized)
        error_match = re.search(r"(?:错误|报错|异常)包含\s*([^，,。]+)", normalized)
        filters: dict[str, list[str]] = {}
        if content_match:
            filters["content_contains"] = [content_match.group(1).strip()]
        if error_match:
            filters["error_contains"] = [error_match.group(1).strip()]
        return filters

    def _split_tool_prompts(self, text: str) -> list[str]:
        if not text:
            return []
        parts = [segment.strip(" ，。；;\n\t") for segment in re.split(r"(?:然后|接着|再|并且|并|;|；)", text) if segment.strip(" ，。；;\n\t")]
        tool_like = [
            part for part in parts
            if any(keyword in part for keyword in ["打开网页", "打开网址", "打开链接", "打开 ", "读文件", "读取文件", "写文件"]) or re.search(r"https?://\S+", part)
        ]
        return tool_like if len(tool_like) >= 2 else []
