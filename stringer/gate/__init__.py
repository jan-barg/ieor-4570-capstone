"""Module 0, the Gate: may a Monitor the Situation event become a video, and can one start now?

    from stringer import gate
    g = gate.Gate()                       # the shared store from GATE_STORE (default stringer_private/gate/)
    g.screen(events)                      # the front page's list (refused events left out)
    d = g.start(event, visitor_id)        # d.ok, d.code, d.message; d.ticket on go
    d.ticket.checkpoint(n_articles=42)    # after the searches
    d.ticket.charge(0.012, "brief_read")  # after each paid step
    d.ticket.finish(video={...})          # or d.ticket.cancel("the job could not start")
    g.view(event_id)                      # what a visitor may be shown: ready, making, has_video, ...

core.py explains the checks and the decisions behind them; rules.py, policy.py, cost.py and store.py
are the parts."""
from .core import (MESSAGES, SHOWN, UNAVAILABLE, ClaimLost, Decision, Gate, Listing, Ticket, TooCostly,
                   VideoOverBudget, tavily_credits_left)
from .store import Conflict, GCSStore, LocalStore, MemoryStore, Store, store_from_env

__all__ = ["Gate", "Decision", "Listing", "Ticket", "MESSAGES", "SHOWN", "UNAVAILABLE", "ClaimLost", "TooCostly",
           "VideoOverBudget", "tavily_credits_left", "Store", "MemoryStore", "LocalStore", "GCSStore", "Conflict",
           "store_from_env"]
