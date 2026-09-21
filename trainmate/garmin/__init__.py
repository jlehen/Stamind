"""Direct Garmin Connect ingestion (see DESIGN_garmin_direct_pull.md).

Three submodules — `client` logs in and fetches, `sync` ingests and orchestrates,
`derived` recomputes the stored PMC and baselines from what was ingested. The training
maths those two run is `trainmate/analytics/`, which reads no database and knows nothing
about Garmin.

Everything is re-exported here so ``from trainmate.garmin import ...`` and
``patch.object(garmin, ...)`` keep working. AGENTS.md calls that debt, not precedent.
"""
from trainmate.config import config
from trainmate.garmin.client import GarminAuthRequired, GarminClient
from trainmate.garmin.derived import (
    _mean_std, pmc_history_start, warmup_cutoff, recompute_derived, _write_derived,
    backfill_tss
)
from trainmate.garmin.sync import (
    _ingest_activities, _ingest_metrics, _int_or_none, connect, pull, _sync_calendar_signals,
    _pull_command, _contiguous_regions, ensure_data, _warn_manual, _remember, reset_memo,
    _safe_round
)
