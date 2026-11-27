"""Every step that has an eval plug-in, by name. Add a line here when a step gets its eval."""
from __future__ import annotations

from .runner import Step


def names() -> list[str]:
    return ["same_story", "brief_read", "brief_onecall", "brief_merge", "brief_sides", "brief_blind", "brief_framing", "claim_wording", "framing_judge", "fact_check", "lens", "script", "gate_policy"]


def get(name: str, **kw) -> Step:
    if name == "same_story":
        from .same_story_eval import SameStoryEval
        return SameStoryEval(**kw)
    if name == "brief_read":
        from .brief_read_eval import BriefReadEval
        return BriefReadEval(**kw)
    if name == "brief_onecall":
        from .brief_onecall_eval import BriefOneCallEval
        return BriefOneCallEval(**kw)
    if name == "brief_merge":
        from .brief_merge_eval import BriefMergeEval
        return BriefMergeEval(**kw)
    if name == "brief_sides":
        from .brief_sides_eval import BriefSidesEval
        return BriefSidesEval(**kw)
    if name == "brief_blind":
        from .brief_blind_eval import BriefBlindEval
        return BriefBlindEval(**kw)
    if name == "brief_framing":
        from .brief_framing_eval import BriefFramingEval
        return BriefFramingEval(**kw)
    if name == "claim_wording":
        from .claim_wording_eval import ClaimWordingEval
        return ClaimWordingEval(**kw)
    if name == "framing_judge":
        from .framing_judge_eval import FramingJudgeEval
        return FramingJudgeEval(**kw)
    if name == "fact_check":
        from .fact_check_eval import FactCheckEval
        return FactCheckEval(**kw)
    if name == "lens":
        from .lens_eval import LensEval
        return LensEval(**kw)
    if name == "script":
        from .script_eval import ScriptEval
        return ScriptEval(**kw)
    if name == "gate_policy":
        from .gate_policy_eval import GatePolicyEval
        return GatePolicyEval(**kw)
    raise KeyError(f"no eval for step '{name}'; known: {', '.join(names())}")
