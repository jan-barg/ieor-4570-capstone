"""The Gate's content check (module 0): the child-victim rule. Made-up events; a fake model."""
import pytest

from stringer.gate import policy


def ev(title, summary="", category="conflict", subtype="armed_attack"):
    return dict(id="test-1", title=title, summary=summary, category=category, subtype=subtype, country="")


class R:
    def __init__(self, text):
        self.text = text


def fake(*answers):
    """A complete() that returns the given answers in turn (an Exception instance is raised)."""
    seen = []

    def complete(messages, name=None, **params):
        seen.append(dict(messages=messages, name=name, params=params))
        a = answers[min(len(seen) - 1, len(answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return R(a)
    complete.seen = seen
    return complete


GOOD = '{"reason": "A wider strike; children among the dead.", "child_role": "victims_among_many", "verdict": "allow"}'


@pytest.mark.parametrize("title,want", [
    ("Gunman Opens Fire at Primary School, Wounding Six", "refuse"),
    ("Drone Strike Kills Boy, 7, in Border Village", "refuse"),
    ("Toddler Dies After Beating by Carer", "refuse"),
    ("Police Arrest Teen Over Planned Concert Attack", "allow"),        # minor as suspect
    ("Shelling Kills 14, Including Three Children", "allow"),          # among a wider toll
    ("School Roof Collapse Kills 20 Pupils", "allow"),                 # disaster
    ("Students March Against Tuition Fees", "allow"),                  # no harm
    ("Central Bank Raises Rates", "allow"),
    ("Man, 24-year-old, Stabbed Outside Bar", "allow"),                # an adult
    ("12-year-old Shot by Police at Checkpoint", "refuse"),            # an age under 18
])
def test_keyword_rule(title, want):
    assert policy.keyword_verdict(ev(title)).verdict == want


def test_keyword_rule_counts_category_disaster():
    assert policy.keyword_verdict(ev("Boy Killed as Storm Hits Coast", category="disaster")).verdict == "allow"


def test_model_answer_is_used_and_the_format_enforced():
    c = fake(GOOD)
    v = policy.judge(ev("Strike kills 20 including children"), c, model="haiku-5-5")
    assert v.verdict == "allow" and v.by == "model" and v.child_role == "victims_among_many" and v.calls == 1
    p = c.seen[0]["params"]
    assert p["response_format"]["json_schema"]["strict"] is True and p["max_tokens"] >= 4000
    assert "Title: Strike kills 20 including children" in c.seen[0]["messages"][-1]["content"]


def test_bad_answer_gets_one_retry_with_a_note():
    c = fake("sure! it's fine", GOOD)
    v = policy.judge(ev("x"), c, model="haiku-5-5")
    assert v.verdict == "allow" and v.retried and v.calls == 2 and not v.fallback
    assert "couldn't be used" in c.seen[1]["messages"][-1]["content"]


def test_unusable_twice_falls_back_to_the_keyword_rule():
    c = fake('{"verdict": "maybe"}', "")
    v = policy.judge(ev("Gunman Wounds Pupils at High School"), c, model="haiku-5-5")
    assert v.fallback and v.by == "code:keywords (fallback)" and v.verdict == "refuse" and v.calls == 2


def test_failed_calls_fall_back_too():
    v = policy.judge(ev("Budget Passes"), fake(TimeoutError("slow"), TimeoutError("slow")), model="m")
    assert v.fallback and v.verdict == "allow" and len(v.errors) == 2


def test_budget_stop_passes_through():
    class BudgetExceeded(RuntimeError):
        pass
    with pytest.raises(BudgetExceeded):
        policy.judge(ev("x"), fake(BudgetExceeded("cap")), model="m")


def test_answers_in_code_fences_or_with_extra_text_are_read():
    assert policy.parse("```json\n" + GOOD + "\n```")["verdict"] == "allow"
    assert policy.parse("Here you go: " + GOOD)["verdict"] == "allow"
    assert policy.problem({"verdict": "Refuse"}) == ""


def test_text_hash_follows_the_text():
    a = ev("Title", "Summary")
    assert policy.text_hash(a) == policy.text_hash(dict(a, report_count=99))
    assert policy.text_hash(a) != policy.text_hash(dict(a, summary="Summary, edited"))


def test_prompt_examples_are_made_up_and_differ_from_the_eval_edge_cases():
    from scripts.build_gate_policy_set import MADE_UP
    prompt = policy.PROMPTS[policy.VERSION].lower()
    for case in MADE_UP:
        assert case[2].lower() not in prompt
