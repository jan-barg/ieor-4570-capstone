"""Every step that has an eval plug-in, by name. Add a line here when a step gets its eval."""
from __future__ import annotations

from .runner import Step


def names() -> list[str]:
    return ["same_story"]


def get(name: str, **kw) -> Step:
    if name == "same_story":
        from .same_story_eval import SameStoryEval
        return SameStoryEval(**kw)
    raise KeyError(f"no eval for step '{name}'; known: {', '.join(names())}")
