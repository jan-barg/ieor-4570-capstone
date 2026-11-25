"""Where the private data lives. Code never stores data next to itself.

STRINGER_PRIVATE overrides the default (../stringer_private next to this code folder)."""
import os
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
PRIVATE = Path(os.environ.get("STRINGER_PRIVATE", CODE.parent / "stringer_private")).resolve()

OUTLETS_CSV = PRIVATE / "outlets" / "outlets.csv"
SIDE_LISTS_CSV = PRIVATE / "outlets" / "side_lists.csv"
FIXTURES_CSV = PRIVATE / "fixtures" / "fixtures_v1.csv"
FIXTURE_LENSES_CSV = PRIVATE / "fixtures" / "fixture_lenses_v1.csv"
ARCHIVE_GZ = PRIVATE / "archive" / "mts-events-2026-11-23.csv.gz"
FROZEN = PRIVATE / "frozen"
STORIES = FROZEN / "stories"
ARTICLE_CACHE = FROZEN / "article_cache"
RAW = FROZEN / "raw"            # every API response, so re-runs cost nothing
RUNS = PRIVATE / "runs"         # local call log (model calls, searches)
EVALS = PRIVATE / "evals"       # eval results (runs/), the model-answer cache (cache/), comparison tables
FIXTURES = PRIVATE / "fixtures"  # hand-made answer keys and the samples they label
OUTLET_SOURCES = PRIVATE / "outlet_labels_tests"
