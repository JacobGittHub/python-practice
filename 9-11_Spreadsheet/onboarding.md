# Onboarding a new sensor export

How to take a raw CSV from a new setup and get the master activity table out of it.

The code is in two files: `sensor_tools.py` holds the logic and knows nothing about any
particular house, and `sensor_config.py` holds one export's labels. Onboarding a new setup
means writing a new config; the tools should not need to change.

Start from `sensor_config_default.py`, which is this structure with empty values and the
reasoning behind each field. Copy it to `sensor_config.py` and fill it in.

---

## Step 1 — Find out what is actually in the export

Never write the config from what the labels are *supposed* to be. Read them out of the file.
Misspellings and inconsistent separators are common and produce silently empty tables.

```python
import pandas as pd

raw = pd.read_csv("YourExport.csv")
raw.columns = ["signal", "date", "time", "sensor_type"]
raw.groupby(["sensor_type", "signal"]).size().sort_values(ascending=False)
```

Read that output for four things:

1. **Misspelled sensor types.** In HomeIntellex-2, `Left_Kitchen` is logged under
   `Onvis_MotioinSensor` while `In_Kitchen` uses the correct spelling, splitting one sensor
   across two type names.
2. **Inconsistent separators.** `Left_Office_Computer` uses underscores,
   `Left-Bedroom-Computer` uses hyphens. Both are real; copy them exactly.
3. **Signals that were renamed partway through.** Check whether a label stops appearing on
   a given date and another starts. The microwave logged `-Open` and `-Vib` for the first
   18 minutes, then `-O/C` for the rest of the week — three names for one signal.
4. **Sensor types covering more than one physical sensor.** `Presence_FP2` is one physical
   sensor reporting eight independent zones, and there is normally one such sensor per
   home. Selecting by sensor type would merge every zone into one meaningless timeline, so
   group presence signals by zone instead. If a future setup has more than one presence
   sensor, zones may need to be attributed to a specific unit — though since a person can
   only be in one place at a time, the single-location logic below may absorb that without
   the attribution being made explicit.

Then check each candidate pair alternates the way you expect:

```python
import sensor_tools as st

sub = st.subset_by_signal(df_sorted, ["Zone-In", "Zone-Out"])
st.check_alternation(sub, "Zone-In", "Zone-Out")
```

An empty result means clean alternation. Violations are not necessarily a problem — they
decide which of the two design patterns below a sensor belongs to.

---

## Step 2 — Write the config

Copy `sensor_config_default.py` and replace the labels. Every entry is one of two shapes.

### Sustained state — a pair of signals

Most sensors. One signal starts the state, another ends it, and the column holds 1 in
between.

```python
VIBRATION_SENSORS = {
    "bike": {"on": "Bike-InUse", "off": "Bike-Stopped"},
}
```

### Momentary event — a single signal

A trigger with no "off": a doorway crossing, a button. The column is 1 only on that row.

```python
PRESENCE_EVENTS = {
    "livingroom_inout": "Livingroom-In/out",
    "bedroom_door": "BedroomDoor",
}
```

A zone can need both. Livingroom has `Occupied`/`Vacant` as a clean state pair **and** a
separate momentary `In/out` crossing. Treating all three as one three-state signal is what
made that zone look incoherent; split into a state plus an event, it reads cleanly.

### Label corrections

Applied at load, before anything else sees the data:

```python
SENSOR_TYPE_FIXES = {"Onvis_MotioinSensor": "Onvis_MotionSensor"}
SIGNAL_TYPE_FIXES = {
    "MicrowaveDoor-Open": "MicrowaveDoor-O/C",   # renamed 2026-09-06
    "MicrowaveDoor-Vib": "MicrowaveDoor-O/C",
}
```

### Register the families

`SENSOR_FAMILIES` is what the master table builder consumes. A new sensor type joins by
being appended here — no change to `sensor_tools.py`.

```python
SENSOR_FAMILIES = [
    (VIBRATION_STATES, None),
    (MOTION_STATES, None),
    (CONTACT_STATES, None),
    (PRESENCE_STATE_COLUMNS, PRESENCE_EVENT_COLUMNS),
]
```

Column names must be unique across families, which is why each family prefixes its names
(`vib_bike`, `presence_bikeside`). Duplicates raise rather than silently overwrite.

`LABEL_COLUMNS` optionally adds a categorical summary of a group of one-hot columns. The
one-hot columns are kept, so both views are available:

```python
LABEL_COLUMNS = {"presence_zone": list(PRESENCE_STATE_COLUMNS)}
```

---

## Step 3 — Build the tables

The whole pipeline, unbroken:

```python
import pandas as pd
import sensor_tools as st
import sensor_config as cfg

# load, with label corrections applied
df_sorted = st.load_sensor_csv(
    "YourExport.csv",
    sensor_type_fixes=cfg.SENSOR_TYPE_FIXES,
    signal_fixes=cfg.SIGNAL_TYPE_FIXES,
)

# confirm the config claims every signal in the export
mapped = set()
for states, events in cfg.SENSOR_FAMILIES:
    for labels in (states or {}).values():
        mapped.update(labels.values())
    mapped.update((events or {}).values())
unmapped = sorted(set(df_sorted["signal"].unique()) - mapped)
assert not unmapped, f"config does not cover: {unmapped}"

# the master table: one row per signal, one column per sensor
master_timeline = st.build_master_timeline(
    df_sorted,
    cfg.SENSOR_FAMILIES,
    cfg.LABEL_COLUMNS,
)

# per-sensor totals
master_summary = st.summarise_timeline(
    master_timeline,
    event_columns=cfg.PRESENCE_EVENT_COLUMNS,
)

# per-sensor activity tables, with the 2 minute chaining rule
activities = {}
for name, labels in cfg.VIBRATION_SENSORS.items():
    sub = st.subset_by_signal(df_sorted, [labels["on"], labels["off"]], telemetry=False)
    activities[f"vib_{name}"] = st.build_activities(sub, labels["on"], labels["off"])

# contact sensors alternate cleanly, so they pair directly with no gap rule
for name, labels in cfg.CONTACT_SENSORS.items():
    sub = st.subset_by_signal(df_sorted, [labels["on"], labels["off"]], telemetry=False)
    activities[f"contact_{name}"] = st.build_paired_activities(sub, labels["on"], labels["off"])
```

Every function prints its own timing. Pass `telemetry=False` to silence one call.

---

## Two tables, two questions

`master_timeline` and `build_activities` disagree on purpose, and it is worth knowing why
before trusting either number.

**`master_timeline` is raw state.** Every on signal flips a column to 1. Bike shows 10
activations because there are 10 `Bike-InUse` signals.

**`build_activities` applies the 2 minute chaining rule.** On/off cycles closer together
than `gap_limit` merge into one activity, on the theory that a rider who stops for 30
seconds at a light has not finished their ride. Bike shows 6.

Use the master timeline for "what was happening at 9pm" and co-occurrence between sensors;
use the activity tables for "how many sessions, how long each."

---

## Choosing gap limits

The gap limit is the knob, and it has no universally right value. Sweep it per sensor:

```python
gap_sweep = st.sweep_all_sensors(
    df_sorted,
    {**cfg.VIBRATION_STATES, **cfg.MOTION_STATES},
    cfg.GAP_LIMIT_SWEEP_MINUTES,   # [0, 1, 2, 3, 4, 5, 6, 7, 8, 15]
)
```

The grid is dense through the range where activity counts actually move, and stops at 15
rather than reaching for 32. A doubling scale looks tidy but spends half its columns on
thresholds no household activity plausibly needs, while skipping the 3–7 minute band where
most of the real structure turns out to be.

Widening the limit can only merge activities, never split them, so every row is
non-increasing:

| sensor | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|
| vib_bike | 12 | 7 | 6 | 6 | 6 | 6 | 6 | 6 | 6 | 6 |
| vib_bedroom_computer | 52 | 40 | 36 | 35 | 33 | 33 | 32 | 29 | 27 | 22 |
| vib_office_computer | 630 | 399 | 284 | 222 | 170 | 131 | 110 | 92 | 75 | 35 |
| vib_microwave | 20 | 19 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 14 |
| motion_kitchen | 375 | 160 | 136 | 123 | 114 | 109 | 106 | 102 | 95 | 77 |
| motion_office | 203 | 133 | 116 | 100 | 95 | 93 | 89 | 87 | 85 | 68 |
| motion_bedroom | 71 | 38 | 33 | 30 | 22 | 18 | 18 | 17 | 13 | 10 |

Read each row for a **plateau**, which the denser grid makes far easier to see.

**Bike** settles at 6 from 2 minutes onward and never moves again — a genuine plateau, so
any value in that range gives the same answer and the choice is not load-bearing.
**Microwave** is flat at 15 across the entire 2–8 band, consistent with its fixed sensor
timeout. **Office computer** falls from 630 to 35 and never settles: there is no natural
session boundary in that signal, so its threshold has to be justified from outside the
data. The motion sensors sit in between, easing downward without a convincing flat run.

That is what participant reports are for. If someone says they ride once a day, pick the
gap limit whose count is nearest to one per day over the logged span. `GAP_LIMITS_MINUTES`
holds one value per sensor, so a sensor with a clear plateau can use it while the rest fall
back to `DEFAULT_GAP_LIMIT_MINUTES`.

Sweeps are cheap — seven sensors across ten thresholds runs in about 240 ms — so there is
no need yet for successive tables to parse their predecessors. That optimisation becomes
worth it if the sweep grid or the export grows by an order of magnitude.

---

## Handling missing alternations

When a sensor logs two on signals with no off between them, something was dropped. There
are two strategies, selectable per call:

```python
st.build_activities(sub, on, off, strategy="inline")     # default
st.build_activities(sub, on, off, strategy="synthetic")
```

- **`inline`** resolves the duplicate during the walk: within `gap_limit` it continues the
  current activity, beyond it closes and opens a new one anchored a minute before.
- **`synthetic`** inserts a phantom on signal into the data first, then chains normally.

On the HomeIntellex-2 export **both produce identical results for all seven on/off
sensors** — same counts, same totals. The dataset cannot distinguish them. `compare_strategies`
is there for when an export finally can.

---

## Estimating location

`presence_zone` reports what the presence sensor claims. The location estimate is a
different thing: a single best guess at which room the person is in, weighing every sensor
in the house. Same shape as `presence_zone`, different question.

### Why one column is the right shape

A person can only be in one place at a time, so a single location per time slot is not a
simplification — it is the constraint the data should satisfy. The raw presence columns do
not satisfy it. In this export **28% of rows have more than one zone active at once**.

Most of that is structural rather than a fault: `presence_livingroom` is a superset zone
overlapping sofa, chair, table and TV. Excluding it leaves **257 genuinely ambiguous rows**,
and those are real multi-zone reports. In half of them the older zone had gone more than
2 minutes without being refreshed, which is the evidence that "most recent activation wins"
is a sound tiebreak. `presence_chair` is the stale one most often (117 times); `presence_sofa`
is most often the fresh winner (145).

### Events, not states

The central idea: **a signal is a timestamped observation of where someone was at that
instant, not a state that stays true.** The most recent observation always wins. Strength
never lets an older signal outrank a newer one.

This is what makes the estimate work, because sensors report departures *late*. A motion
sensor may not send its off signal until a minute or two after the person left the room —
by which time they have already triggered a presence zone somewhere else. Anything that
weighs sensor *state* rather than signal *events* loses that race and keeps the person in
the room they left.

So the priority list does not decide which of two signals wins. It decides **whether a
signal is an observation at all**:

```python
SIGNAL_PRIORITY = [
    # tier 0, positive: vibration "on", contact "on", motion "on"
    # tier 1, positive: contact "off", presence events, presence state "on"
    # tier 2, negative: presence state "off"
    # tier 3, negative: vibration "off", motion "off"
]
LOCATION_POSITIVE_TIERS = 2
```

The top two tiers are positive evidence: an event saying a person was here, now. They move
the estimate. The bottom two are negative: a zone reporting itself vacated. They place
nobody anywhere, so they can only *falsify* — clearing the estimate to `unknown` when they
name the room currently believed occupied.

The split rests on what each signal can be caused by. A vibration or contact "on" needs
someone to physically move an object. An "off" usually fires on a fixed timeout, so it
reports that nothing happened — equally true of every room the person is *not* in.

Only signals carrying locational evidence need a `SIGNAL_LOCATIONS` entry; anything absent
never moves the estimate.

### On merging the top two tiers

**Merging tiers 0 and 1 changes nothing, and this is verified, not assumed.** Running the
export with `[tier0, tier1]` and with `[tier0 + tier1]` produces byte-identical location
columns.

The reason is structural: each row carries exactly one signal, so two positive tiers never
compete for the same instant. Rank could only change an outcome by *suppressing* a later
event, which is precisely the behaviour an event model rejects. The two tiers are kept
separate for readability — they document a real difference in how much you would trust the
signal — but they are behaviourally one tier.

**There is also no race condition, and no need for one fixed order.** Recency decides
every contest and each row holds one signal, so the output is deterministic whatever order
the tiers are written in. The only ordering that matters is the positive/negative boundary
set by `LOCATION_POSITIVE_TIERS`.

### The two windows

Negative signals need care, for opposite reasons at two timescales.

**`LOCATION_ZONE_EXIT_GRACE_SECONDS`** handles the short end. Rooms hold several zones, so
a zone exit usually means the person crossed their own livingroom, not that they left it.
Falsifying on every zone exit makes the estimate flicker: `Sofa-Left` at 17:08:53,
`TableSide-In` 8 seconds later. Measured on this export, **1544 of 1680 vacancy-driven
unknowns were resolved by the same room**, at a median of 7 seconds. The grace window
ignores a zone exit if another zone of that room speaks up within it.

| grace | location changes | unknown |
|---|---|---|
| off | 4029 | 39.5% |
| 5 s | 2608 | 39.3% |
| **30 s** | **1967** | **38.3%** |
| 60 s | 1733 | 37.2% |
| 120 s | 1463 | 34.7% |

At 30 s the change count halves while the unknown share barely moves, which is the
signature of removing artifacts rather than suppressing real transitions. Unknown stretches
drop from 1681 to 624 and their median rises from 7 s to 2 min — what remains is real
silence, not zone-hopping.

**`LOCATION_DECAY_MINUTES`** handles the long end. Without it the last signal before a
silent night holds that room until morning. Long silences dominate here: **gaps over an
hour are 50% of the logged span**, and 9 of the 15 longest begin with `Livingroom-Vacant`,
which is the sensor saying the room emptied and then nothing happening for six hours.

Between them, **38% of the week is `unknown`** — and that is the honest answer. This is a
5.5-day export with 5319 signals; most of it is nobody home or asleep.

```python
location_estimate = st.estimate_location(
    df_sorted,
    cfg.SIGNAL_LOCATIONS,
    cfg.SIGNAL_PRIORITY,
    positive_tiers=cfg.LOCATION_POSITIVE_TIERS,
    decay=pd.Timedelta(minutes=cfg.LOCATION_DECAY_MINUTES),
    zone_exit_grace=pd.Timedelta(seconds=cfg.LOCATION_ZONE_EXIT_GRACE_SECONDS),
)
```

Current output: unknown 38.3%, bedroom 32.1%, garage 11.9%, office 8.1%, livingroom 6.9%,
kitchen 2.6%.

### A known limitation: decay is evaluated lazily

**The garage figure is not trustworthy, and the reason is worth understanding.** 15 open
events should not produce 15 hours, and 11h20m of that total is a single stretch:

```
07:52:01  GarageEntrance_Open    -> garage    (person leaves for the day)
07:56:10  Livingroom-Vacant      -> garage    held for 11h16m
19:12:20  GarageEntrance_Open    -> garage    (person returns)
```

Decay is checked when a row is *processed*, so a 30-minute decay cannot expire an estimate
during an 11-hour silence — the next row that would trigger the check does not arrive until
the silence ends. The estimate is correct at every row; the problem is that a row's value
is carried forward until the next one, and nothing marks the interval between them.

This is a resampling issue rather than a logic error, and it does not affect per-row
analysis. It matters for any duration or percentage computed by forward-filling, which
includes the time shares above. The fix is to emit explicit `unknown` rows at decay
boundaries, or to resample onto a fixed grid before integrating time. Left as-is for now
since the row-level estimate is what feeds the master table.

Note also that `GarageEntrance_Close` is treated as positive evidence of being in the
garage, which is wrong when the door is closed from inside the house — consistent with your
own note that the garage door is a poor location proxy.

### One-hot without overlap

For tensor construction, where a label column cannot be used:

```python
location_one_hot = st.one_hot_location(location_estimate)
```

Exactly one column is 1 per row. The mutual exclusivity is structural, not enforced after
the fact: these columns are derived from a single committed estimate, not from the raw zone
signals, so no two locations can overlap in a time slot by construction.

---

## Known traps

**Momentary columns have no meaningful duration.** A momentary column stays 1 until the
next signal from *any* sensor, so its "time active" measures that gap. `summarise_timeline`
reports `NaT` for columns named in `event_columns` rather than a misleading number. Use the
count.

**Activation counts can be lower than raw signal counts.** Sofa has 611 `Sofa-Sit` signals
but 603 activations. The difference is repeated on-signals with no off between them, which
correctly do not re-trigger a rise. Not a bug, and it is the same duplicate problem the
strategies above exist to handle.

**Sensor timeouts can masquerade as measurements.** Every microwave `NoVib` lands 57–64
seconds after its `O/C`, all week, with almost no variance. That is a fixed timeout, not a
measurement of when vibration stopped. Its event count and start times are trustworthy; its
durations are not. Check for suspiciously constant durations before reporting them.

**The display variant is strings.** `master_timeline_display` renders 1 as `####1` for
legibility in a table view, which makes those columns object dtype. Keep using
`master_timeline` for arithmetic.

**Wide tables render differently depending on how the cell is run.** VS Code intercepts a
DataFrame returned as a cell's result and renders it in an interactive data grid, which
gives every column a fixed minimum width — a 10-column table of two-digit numbers then
scrolls off-screen. Running the notebook through `nbconvert` produces a plain HTML table
instead, which sizes to its content, so the same notebook looks different depending on who
ran it. The grid only intercepts a *returned* DataFrame, so wrapping the value escapes it:

```python
gap_sweep                       # interactive grid, very wide
display(gap_sweep.style)        # plain HTML table, sized to content
print(gap_sweep)                # plain text
```

Styler renders all 21 columns of the master table on pandas 3.0.5, where
`styler.render.max_columns` defaults to `None`. Older pandas defaulted it to 20 and would
silently drop the rest, so check the option if a styled table ever looks short a sensor.
`jupyter.enableTableViewer: false` turns the grid off globally if you would rather never
see it.

---

## Checklist

- [ ] Ran the groupby and read the real labels out of the CSV
- [ ] Checked for misspellings, separator drift, mid-export renames, multi-zone sensor types
- [ ] Ran `check_alternation` on each pair
- [ ] Split any zone that mixes a state pair with a momentary signal
- [ ] Wrote `SENSOR_TYPE_FIXES` and `SIGNAL_TYPE_FIXES`
- [ ] Registered every family in `SENSOR_FAMILIES` with unique column prefixes
- [ ] `unmapped` came back empty
- [ ] Ran the gap limit sweep on a grid dense enough to show plateaus, and chose a value
      per sensor from a plateau or a participant report
- [ ] Mapped every locational signal in `SIGNAL_LOCATIONS` and placed it in a
      `SIGNAL_PRIORITY` tier
- [ ] Set `LOCATION_POSITIVE_TIERS` so that "off" signals only falsify
- [ ] Swept `LOCATION_ZONE_EXIT_GRACE_SECONDS` and confirmed the change count drops
      without the unknown share moving much
- [ ] Checked the gap distribution before choosing `LOCATION_DECAY_MINUTES`
- [ ] Sanity-checked the resulting time shares against rooms the participant plausibly
      spends time in, remembering that long silences are not attributable
- [ ] Checked how often presence zones overlap, and that the one-hot location columns are
      mutually exclusive
