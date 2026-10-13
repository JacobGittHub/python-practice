"""Helpers for turning raw HomeIntellex sensor logs into per-sensor activity tables.

The first CSV column holds a sensor state transition rather than a place, so it is called
`signal` here. Column names, signal labels and sensor-type labels vary between exports, so
everything takes them as arguments rather than hardcoding this dataset's spellings.
"""

import time
from functools import wraps

import pandas as pd

DEFAULT_GAP_LIMIT = pd.Timedelta(minutes=2)
DEFAULT_START_OFFSET = pd.Timedelta(minutes=1)


def timed(func):
    """Print how long the wrapped call took. Disable with telemetry=False."""

    @wraps(func)
    def wrapper(*args, telemetry=True, **kwargs):
        if not telemetry:
            return func(*args, **kwargs)
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        n_in = len(args[0]) if args and isinstance(args[0], pd.DataFrame) else "-"
        n_out = len(result) if hasattr(result, "__len__") else "?"
        print(f"[{func.__name__}] n_in={n_in} n_out={n_out} {elapsed * 1000:.2f} ms")
        return result

    return wrapper


@timed
def load_sensor_csv(
    path,
    columns=("signal", "date", "time", "sensor_type"),
    date_format="%m/%d/%Y",
    sensor_type_fixes=None,
    signal_fixes=None,
):
    """Read a raw export and return it with a combined `datetime` column.

    `sensor_type_fixes` and `signal_fixes` each map a label as logged to its corrected
    form, covering misspellings and signals that were renamed partway through logging.
    """
    df = pd.read_csv(path)
    df.columns = list(columns)
    if sensor_type_fixes:
        df["sensor_type"] = df["sensor_type"].replace(sensor_type_fixes)
    if signal_fixes:
        df["signal"] = df["signal"].replace(signal_fixes)
    df["datetime"] = pd.to_datetime(df["date"], format=date_format) + pd.to_timedelta(df["time"])
    return df.sort_values("datetime").reset_index(drop=True)


@timed
def subset_by_signal(df, signals, signal_col="signal", datetime_col="datetime"):
    """Rows whose signal is in `signals`, sorted by time."""
    return (
        df[df[signal_col].isin(signals)]
        .sort_values(datetime_col)
        .reset_index(drop=True)
    )


@timed
def subset_by_sensor_type(df, sensor_type, sensor_type_col="sensor_type", datetime_col="datetime"):
    """Rows for one sensor type, sorted by time.

    Only meaningful when a sensor type maps to a single physical sensor. Presence_FP2
    covers many independent zones in these exports, so prefer subset_by_signal there.
    """
    return (
        df[df[sensor_type_col] == sensor_type]
        .sort_values(datetime_col)
        .reset_index(drop=True)
    )


def _activities_synthetic(labels, times, on_label, off_label, gap_limit, start_offset):
    """Insert a synthetic on-event between consecutive off-events, then chain."""
    synthetic = []
    if labels and labels[0] == off_label:
        synthetic.append((times[0] - start_offset, on_label))

    for i in range(len(labels) - 1):
        if labels[i] == off_label and labels[i + 1] == off_label:
            offset = start_offset
            synth_time = times[i + 1] - offset
            while synth_time <= times[i]:
                offset = offset / 2
                synth_time = times[i + 1] - offset
            synthetic.append((synth_time, on_label))

    if synthetic:
        merged = sorted(list(zip(times, labels)) + synthetic, key=lambda pair: pair[0])
        times = [t for t, _ in merged]
        labels = [lab for _, lab in merged]

    events = []
    event_start = None
    last_off = None
    for label, t in zip(labels, times):
        if label == on_label:
            if event_start is None:
                event_start = t
            elif last_off is not None and (t - last_off) > gap_limit:
                events.append({"start": event_start, "duration": last_off - event_start})
                event_start = t
            last_off = None
        elif label == off_label:
            last_off = t

    if event_start is not None and last_off is not None:
        events.append({"start": event_start, "duration": last_off - event_start})
    return events


def _activities_inline(labels, times, on_label, off_label, gap_limit, start_offset):
    """Resolve duplicate off-events against the gap rule without adding rows."""
    events = []
    event_start = None
    last_off = None

    for label, t in zip(labels, times):
        if label == on_label:
            if event_start is None:
                event_start = t
            elif last_off is not None and (t - last_off) > gap_limit:
                events.append({"start": event_start, "duration": last_off - event_start})
                event_start = t
            last_off = None
        elif label == off_label:
            if last_off is not None:
                # previous row was also an off-event: no on-event came between them
                if (t - last_off) <= gap_limit:
                    last_off = t
                else:
                    events.append({"start": event_start, "duration": last_off - event_start})
                    event_start = t - start_offset
                    last_off = t
            else:
                if event_start is None:
                    event_start = t - start_offset
                last_off = t

    if event_start is not None and last_off is not None:
        events.append({"start": event_start, "duration": last_off - event_start})
    return events


_STRATEGIES = {"synthetic": _activities_synthetic, "inline": _activities_inline}


@timed
def build_activities(
    df,
    on_label,
    off_label,
    strategy="inline",
    gap_limit=DEFAULT_GAP_LIMIT,
    start_offset=DEFAULT_START_OFFSET,
    signal_col="signal",
    datetime_col="datetime",
):
    """Chain on/off pairs into activities, merging them across gaps of <= `gap_limit`.

    `strategy` selects how a missing on-event between two off-events is handled:
    "synthetic" inserts a phantom on-event row first, "inline" resolves it during the walk.
    """
    if strategy not in _STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(_STRATEGIES)}, got {strategy!r}")

    events = _STRATEGIES[strategy](
        df[signal_col].tolist(),
        df[datetime_col].tolist(),
        on_label,
        off_label,
        gap_limit,
        start_offset,
    )
    activities = pd.DataFrame(events, columns=["start", "duration"])
    if not activities.empty:
        activities["end"] = activities["start"] + activities["duration"]
    return activities


@timed
def compare_strategies(df, on_label, off_label, **kwargs):
    """Run both strategies and summarise where they disagree."""
    synthetic = build_activities(df, on_label, off_label, strategy="synthetic", telemetry=False, **kwargs)
    inline = build_activities(df, on_label, off_label, strategy="inline", telemetry=False, **kwargs)
    return pd.DataFrame(
        [{
            "synthetic_activities": len(synthetic),
            "inline_activities": len(inline),
            "identical": synthetic.equals(inline),
            "synthetic_total": synthetic["duration"].sum() if not synthetic.empty else pd.Timedelta(0),
            "inline_total": inline["duration"].sum() if not inline.empty else pd.Timedelta(0),
        }]
    )


@timed
def check_alternation(df, on_label, off_label, signal_col="signal", datetime_col="datetime"):
    """Report every place the on/off sequence fails to alternate.

    Contact sensors should alternate perfectly; each returned row is a violation.
    """
    labels = df[signal_col].tolist()
    times = df[datetime_col].tolist()

    problems = []
    if labels and labels[0] == off_label:
        problems.append({"index": 0, "datetime": times[0], "issue": "sequence starts with off-event"})

    for i in range(len(labels) - 1):
        if labels[i] == labels[i + 1]:
            problems.append({
                "index": i + 1,
                "datetime": times[i + 1],
                "issue": f"repeated {labels[i + 1]}",
                "gap": times[i + 1] - times[i],
            })

    if labels and labels[-1] == on_label:
        problems.append({
            "index": len(labels) - 1,
            "datetime": times[-1],
            "issue": "sequence ends with unclosed on-event",
        })

    return pd.DataFrame(problems)


@timed
def build_timeline(
    df,
    states,
    events=None,
    signal_col="signal",
    datetime_col="datetime",
):
    """One row per signal, one column per sensor, showing every sensor's state at that instant.

    `states` maps a column name to {"on": ..., "off": ...}; that column holds 1 from the on
    signal until the off signal arrives. `events` maps a column name to a single momentary
    signal, whose column is 1 only on the row where it fired. Sensors carry their last known
    value forward and start at 0 before their first signal.
    """
    events = events or {}

    on_lookup = {labels["on"]: name for name, labels in states.items()}
    off_lookup = {labels["off"]: name for name, labels in states.items()}
    event_lookup = {signal: name for name, signal in events.items()}

    tracked = set(on_lookup) | set(off_lookup) | set(event_lookup)
    sub = df[df[signal_col].isin(tracked)].sort_values(datetime_col)

    columns = list(states) + list(events)
    current = {name: 0 for name in columns}
    rows = []

    for signal, t in zip(sub[signal_col], sub[datetime_col]):
        for name in events:
            current[name] = 0

        if signal in on_lookup:
            current[on_lookup[signal]] = 1
        elif signal in off_lookup:
            current[off_lookup[signal]] = 0
        elif signal in event_lookup:
            current[event_lookup[signal]] = 1

        rows.append({"datetime": t, "signal": signal, **current})

    timeline = pd.DataFrame(rows, columns=["datetime", "signal"] + columns)
    if not timeline.empty:
        timeline[columns] = timeline[columns].astype("int8")
    return timeline.reset_index(drop=True)


def _collect_states_and_events(families):
    """Flatten the config families into one states map and one events map.

    `families` is an iterable of (states, events) pairs. Column names must not collide
    across families, since they all land in the same table.
    """
    states, events = {}, {}
    for family_states, family_events in families:
        for name, labels in (family_states or {}).items():
            if name in states or name in events:
                raise ValueError(f"duplicate column name across sensor families: {name!r}")
            states[name] = labels
        for name, signal in (family_events or {}).items():
            if name in states or name in events:
                raise ValueError(f"duplicate column name across sensor families: {name!r}")
            events[name] = signal
    return states, events


@timed
def build_master_timeline(
    df,
    families,
    label_columns=None,
    signal_col="signal",
    datetime_col="datetime",
):
    """Every sensor in the house on one shared timeline, one column per sensor.

    `families` is an iterable of (states, events) pairs covering each sensor family, so a
    new sensor type is added by appending its config rather than changing this function.

    `label_columns` optionally adds a categorical column summarising a group of one-hot
    columns: it maps a new column name to the list of columns it summarises. The value is
    the name of the active column, "none" when all are 0, or names joined by "+" when
    several are active at once. The one-hot columns are kept alongside it.
    """
    states, events = _collect_states_and_events(families)
    timeline = build_timeline(
        df, states, events, signal_col=signal_col, datetime_col=datetime_col, telemetry=False
    )

    for new_col, source_cols in (label_columns or {}).items():
        missing = [c for c in source_cols if c not in timeline.columns]
        if missing:
            raise ValueError(f"label column {new_col!r} references unknown columns: {missing}")
        active = timeline[source_cols].astype(bool)
        timeline[new_col] = [
            "+".join(cols) if (cols := [c for c in source_cols if row[c]]) else "none"
            for _, row in active.iterrows()
        ]

    return timeline


@timed
def summarise_timeline(timeline, columns=None, event_columns=(), datetime_col="datetime"):
    """Per-column activation count and total time held active.

    A momentary column holds 1 only until the next signal from any sensor arrives, so its
    duration measures that gap rather than a real span. Name those columns in
    `event_columns` and their duration is reported as NaT instead of a misleading number.
    """
    columns = columns or [
        c for c in timeline.columns
        if c not in (datetime_col, "signal") and timeline[c].dtype.kind in "iu"
    ]
    event_columns = set(event_columns)
    held = timeline[datetime_col].diff().shift(-1)
    span = timeline[datetime_col].iloc[-1] - timeline[datetime_col].iloc[0]

    rows = []
    for col in columns:
        is_event = col in event_columns
        total = pd.NaT if is_event else held[timeline[col] == 1].sum()
        # a momentary column fires once per row it is set on; a state column only counts
        # the transitions from 0 to 1, so repeated on-signals do not inflate the total
        activations = int((timeline[col] == 1).sum()) if is_event else int((timeline[col].diff() == 1).sum())
        rows.append({
            "sensor": col,
            "kind": "event" if is_event else "state",
            "activations": activations,
            "time_active": total,
            "pct_of_span": None if is_event else round(total / span * 100, 2) if span else 0.0,
        })
    return pd.DataFrame(rows).set_index("sensor")


def _signal_priority_lookup(priority):
    """Map each signal to its tier, given `priority` as a list of tiers.

    Each tier is a list of signals that carry equal weight. Earlier tiers are stronger
    evidence of where a person is, so index 0 is the most trustworthy.
    """
    lookup = {}
    for rank, tier in enumerate(priority):
        for signal in tier:
            if signal in lookup:
                raise ValueError(f"signal {signal!r} appears in more than one priority tier")
            lookup[signal] = rank
    return lookup


@timed
def estimate_location(
    df,
    signal_locations,
    priority,
    positive_tiers=2,
    decay=None,
    zone_exit_grace=None,
    signal_col="signal",
    datetime_col="datetime",
    unknown="unknown",
):
    """Best guess at which single room a person is in, at every row.

    A signal is treated as a timestamped *observation* of where someone was at that
    instant, not as a state that stays true. The most recent observation therefore wins
    outright; an older one never outranks it, however strong it was. This matters because
    sensors report leaving a room late: a motion sensor may not send its off signal until
    a minute after the person left, by which time another sensor has already observed them
    somewhere else. Ranking by strength alone would let the stale room win that race.

    Priority decides which signals count as observations at all, not which of two
    observations wins. Signals in the first `positive_tiers` tiers are positive evidence
    and move the estimate. Signals in the remaining tiers are evidence of *absence*: they
    say a zone was vacated, not that anyone is there. Those only falsify, clearing the
    estimate to `unknown`, and are otherwise ignored.

    A falsifying signal clears the estimate only when it rules out the whole room. Several
    zones usually share a room, and leaving one zone for another says nothing about having
    left the room: `Sofa-Left` followed 8 seconds later by `TableSide-In` is someone
    crossing their own livingroom, not a person of unknown whereabouts. `zone_exit_grace`
    is how long a room is given to re-confirm itself: a falsifying signal is ignored if a
    positive observation of that same room arrived within that window, since the person is
    evidently still moving around in it.

    `decay` optionally expires an observation: once nothing has been seen for that long,
    the estimate reverts to `unknown` rather than holding a room through a silent night.
    Highly recommended, since long silences dominate these exports.

    Returns the datetime, the driving signal, the estimated location, the tier of the
    observation behind it, and how old that observation is.
    """
    rank_of = _signal_priority_lookup(priority)
    signals = df[signal_col].tolist()
    times = df[datetime_col].tolist()

    ranks = [rank_of.get(s) for s in signals]
    locations = [signal_locations.get(s) for s in signals]
    positive = [r is not None and l is not None and r < positive_tiers
                for r, l in zip(ranks, locations)]

    # For each row, when the same room is next positively observed. A zone exit that is
    # about to be followed by another zone of the same room is someone moving within it.
    next_same_room = [None] * len(signals)
    if zone_exit_grace is not None:
        upcoming = {}
        for i in range(len(signals) - 1, -1, -1):
            next_same_room[i] = upcoming.get(locations[i])
            if positive[i]:
                upcoming[locations[i]] = times[i]

    held_location, held_rank, held_time = unknown, None, None
    rows = []

    for i, (signal, t) in enumerate(zip(signals, times)):
        if (
            decay is not None
            and held_time is not None
            and (t - held_time) > decay
            and held_location != unknown
        ):
            held_location, held_rank, held_time = unknown, None, None

        rank, location = ranks[i], locations[i]
        if rank is not None and location is not None:
            if positive[i]:
                # an observation: the newest one always wins
                held_location, held_rank, held_time = location, rank, t
            elif location == held_location:
                # a zone of this room reported itself vacated. Only believe the person
                # left the room if no other zone of it speaks up within the grace window.
                reconfirmed = (
                    zone_exit_grace is not None
                    and next_same_room[i] is not None
                    and (next_same_room[i] - t) <= zone_exit_grace
                )
                if not reconfirmed:
                    held_location, held_rank, held_time = unknown, None, t

        rows.append({
            datetime_col: t,
            signal_col: signal,
            "location": held_location,
            "evidence_rank": held_rank,
            "evidence_age": (t - held_time) if held_time is not None else pd.NaT,
        })

    return pd.DataFrame(rows)


@timed
def one_hot_location(estimate, location_col="location", prefix="at_", exclude=("unknown",)):
    """Turn a single-location column into mutually exclusive one-hot columns.

    Exactly one column is 1 per row, so no two locations overlap in a time slot. Values
    in `exclude` get no column of their own; those rows are all-zero.
    """
    values = [v for v in pd.unique(estimate[location_col]) if v not in set(exclude)]
    out = pd.DataFrame(index=estimate.index)
    for value in sorted(values):
        out[f"{prefix}{value}"] = (estimate[location_col] == value).astype("int8")
    return out


@timed
def gap_limit_sweep(
    df,
    on_label,
    off_label,
    gap_limits,
    strategy="inline",
    signal_col="signal",
    datetime_col="datetime",
    **kwargs,
):
    """How the activity count for one sensor responds to the chaining threshold.

    Widening the gap limit can only merge activities, never split them, so the count is
    monotonically non-increasing. A plateau means the threshold has stopped mattering.
    """
    rows = []
    for gap in gap_limits:
        gap = gap if isinstance(gap, pd.Timedelta) else pd.Timedelta(minutes=gap)
        activities = build_activities(
            df, on_label, off_label,
            strategy=strategy, gap_limit=gap,
            signal_col=signal_col, datetime_col=datetime_col,
            telemetry=False, **kwargs,
        )
        rows.append({
            "gap_limit_min": gap.total_seconds() / 60,
            "activities": len(activities),
            "total_time": activities["duration"].sum() if not activities.empty else pd.Timedelta(0),
            "median_duration": activities["duration"].median() if not activities.empty else pd.NaT,
        })
    return pd.DataFrame(rows).set_index("gap_limit_min")


@timed
def sweep_all_sensors(
    df,
    sensors,
    gap_limits,
    strategy="inline",
    signal_col="signal",
    datetime_col="datetime",
):
    """Run `gap_limit_sweep` for every sensor, as one table of counts.

    `sensors` maps a column name to {"on": ..., "off": ...}. Rows are sensors, columns
    are gap limits in minutes, so the value is the activity count at that threshold.
    """
    counts = {}
    for name, labels in sensors.items():
        sub = subset_by_signal(
            df, [labels["on"], labels["off"]],
            signal_col=signal_col, datetime_col=datetime_col, telemetry=False,
        )
        sweep = gap_limit_sweep(
            sub, labels["on"], labels["off"], gap_limits,
            strategy=strategy, signal_col=signal_col, datetime_col=datetime_col,
            telemetry=False,
        )
        counts[name] = sweep["activities"]
    return pd.DataFrame(counts).T.rename_axis("sensor")


@timed
def build_paired_activities(df, on_label, off_label, signal_col="signal", datetime_col="datetime"):
    """Pair each on-event with the next off-event, assuming clean alternation.

    Rows where that assumption breaks are marked in the `clean` column rather than dropped.
    """
    labels = df[signal_col].tolist()
    times = df[datetime_col].tolist()

    events = []
    open_time = None
    for label, t in zip(labels, times):
        if label == on_label:
            if open_time is not None:
                events.append({"start": open_time, "duration": pd.NaT, "clean": False})
            open_time = t
        elif label == off_label:
            if open_time is None:
                events.append({"start": pd.NaT, "end": t, "duration": pd.NaT, "clean": False})
            else:
                events.append({"start": open_time, "duration": t - open_time, "clean": True})
                open_time = None

    if open_time is not None:
        events.append({"start": open_time, "duration": pd.NaT, "clean": False})

    activities = pd.DataFrame(events, columns=["start", "duration", "clean"])
    if not activities.empty:
        activities["end"] = activities["start"] + activities["duration"]
    return activities
