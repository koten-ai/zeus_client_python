"""Agent hook extension surface."""
from dataclasses import dataclass
import re
from typing import List, Optional


@dataclass
class AgentDecision:
    """Return this from a hook when you want to influence the agent loop."""
    stop: bool = False
    reason: Optional[str] = None
    force_return: Optional[str] = None          # if set, end the turn with this summary
    inject_messages: Optional[List[dict]] = None  # messages to splice into the conversation


# Patterns that suggest prompt dump / secrets exfil (hooks baseline — ZC-WISH-013).
_PROMPT_DUMP_RE = re.compile(
    r"(system\s*prompt|show\s*(me\s*)?(your|the)\s*(rules|instructions|prompt)|"
    r"ignore\s*(all\s*)?(previous|prior|system)|"
    r"reveal\s*(hidden|internal)|dump\s*(the\s*)?(prompt|catalog))",
    re.I,
)
_SECRETS_RE = re.compile(
    r"(api[_-]?key|secret[_-]?key|bearer\s+[a-z0-9]|password\s*[:=])",
    re.I,
)


class AgentHooks:
    """Subclass this (or just implement the methods you care about) and
    pass an instance to run_agent(..., hooks=MyHooks()).

    This is the supported way to do crawl / walk / run on top of Zeus.
    """

    async def observe(self, event: str, data: dict):
        """CRAWL + WALK primitive.

        Called at many points in the loop with structured data. All of the
        events below are emitted by the agent loop (in roughly this order):
          - "run_start"          {ctx, has_prior_turns}
          - "contract_status"    {contract_id, status, ctx}
          - "round_start"        {round, ctx}
          - "ai_response"        {round, response, ctx}
          - "tool_call_planned"  {round, name, args, ctx}   (per planned tool call)
          - "zeus_result"        {round, name, args, status, result_text, result_json, ctx}
          - "round_end"          {round, answer_ready, ctx}
          - "final_answer"       {answer, ctx}
          - "policy_decision"    {policy, flags, hooks_jailbreak_score, ctx}

        For crawl: just log everything.
        For walk:  if event == "zeus_result" and "high_margin" in str(data): ...
        """
        pass

    async def before_zeus_dispatch(self, name: str, args: dict, ctx: dict) -> dict:
        """WALK / RUN around the AI's plan for a tool.

        You can mutate args (restrict, add filters, etc.).
        """
        return args

    async def after_zeus_dispatch(
        self, name: str, args: dict, status: int, result_text: str, ctx: dict
    ) -> str:
        """WALK / RUN after Zeus returns, before the AI sees the result.

        Return the (possibly rewritten) text that will be turned into the
        tool message for the AI.
        """
        return result_text

    async def on_ai_response(self, response: dict, ctx: dict) -> Optional[AgentDecision]:
        """RUN point: after we got a reply from the AI (may contain tool_calls).

        Return an AgentDecision to stop the turn, force a return, etc.
        """
        return None

    async def on_round_start(self, round_num: int, ctx: dict) -> Optional[AgentDecision]:
        """RUN point: beginning of a new round, before calling the AI."""
        return None

    async def should_continue(self, round_num: int, messages: list, ctx: dict) -> bool:
        """Simple RUN guard, called at the end of each round (after the tool
        results are back). Return False to stop the loop early — e.g. to cap
        cost, enforce a per-turn round budget, or bail out once a condition is
        met. Default returns True (no change to normal behavior)."""
        return True

    def score_jailbreak(self, ctx: dict) -> float:
        """Client-side jailbreak score 0.0–1.0 (ZC-WISH-014).

        **Never** overwrite model ``jail_break_attempt`` — store separately as
        ``hooks_jailbreak_score``.
        """
        user_msg = str((ctx or {}).get("user_msg") or "")
        score = 0.0
        if _PROMPT_DUMP_RE.search(user_msg):
            score = max(score, 0.85)
        if _SECRETS_RE.search(user_msg):
            score = max(score, 0.7)
        # Denied / sensitive tool names attempted this turn
        denied = (ctx or {}).get("denied_verbs") or []
        if denied:
            score = max(score, 0.6)
        return min(1.0, float(score))

    def must_refuse(self, ctx: dict) -> bool:
        """Hard refuse even if the model cooperates (prompt dump / secrets)."""
        return self.score_jailbreak(ctx) >= 0.85


# Back-compat module-level hooks (still work, for simple cases).
# The run_agent loop will call the instance hooks if provided, falling
# back to these globals so existing customizations keep working.
#
# For a real SDK experience, prefer passing an explicit `hooks=YourHooks()`
# when you call run_agent directly (see the Crawl/Walk/Run section in the README).

async def before_zeus_dispatch(name, args, ctx):
    return args


async def after_zeus_dispatch(name, args, status, result_text, ctx):
    return result_text
