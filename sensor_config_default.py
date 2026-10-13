"""Template config for onboarding a new sensor export.

Copy to `sensor_config.py` and fill in from the real labels in the new CSV. Do not write
these from what the labels are supposed to be: read them out of the file first, as
`onboarding.md` Step 1 describes. Misspellings and separator drift are common and produce
silently empty tables rather than errors.

Every dict below is empty or holds a neutral default. `sensor_tools.py` never needs to
change to onboard a new house; only this file does.
"""

# --------------------------------------------------------------------------------------
# Label corrections, applied at load before anything else sees the data
# --------------------------------------------------------------------------------------

# Misspelled sensor types: {as logged: corrected}. One physical sensor logged under two
# spellings would otherwise split into two.
SENSOR_TYPE_FIXES = {}

# Signals renamed partway through logging: {as logged: corrected}. Check whether a label
# stops appearing on some date and another starts on the same date.
SIGNAL_TYPE_FIXES = {}

# --------------------------------------------------------------------------------------
# Sensors, grouped by design pattern
# --------------------------------------------------------------------------------------
# Each entry is one of two shapes:
#   sustained state -> {"on": <signal>, "off": <signal>}, column holds 1 in between
#   momentary event -> a single signal, column is 1 only on that row
#
# A zone can need both. If a "three-state" sensor looks incoherent, check whether it is
# really a clean on/off pair plus a separate momentary signal.

# Fires while an object is physically moving. The "on" is strong evidence a person is
# there; the "off" is usually a fixed timeout, so treat its timing with suspicion.
VIBRATION_SENSORS = {
    # "bike": {"on": "Bike-InUse", "off": "Bike-Stopped"},
}

# Fires while something is moving in the room. Same asymmetry: "on" is trustworthy,
# "off" means only that nothing has moved recently.
MOTION_SENSORS = {
    # "kitchen": {"on": "In_Kitchen", "off": "Left_Kitchen"},
}

# Open/close on a door or drawer. These usually alternate perfectly, so they pair
# directly with `build_paired_activities` and need no gap rule.
CONTACT_SENSORS = {
    # "fridge_door": {"on": "FridgeDoor_Open", "off": "FridgeDoor_Close"},
}

# A presence sensor typically covers several independent zones under one sensor_type, so
# group these by zone rather than by sensor type. Selecting by sensor_type would merge
# every zone into one meaningless timeline.
PRESENCE_STATES = {
    # "sofa": {"on": "Sofa-Sit", "off": "Sofa-Left"},
}

PRESENCE_EVENTS = {
    # "bedroom_door": "BedroomDoor",
}

# --------------------------------------------------------------------------------------
# Column naming and family registry
# --------------------------------------------------------------------------------------
# Prefixes keep names unique across families and keep the master table readable about
# which sensor a column came from. Duplicates raise rather than silently overwrite.

VIBRATION_STATES = {f"vib_{name}": labels for name, labels in VIBRATION_SENSORS.items()}
MOTION_STATES = {f"motion_{name}": labels for name, labels in MOTION_SENSORS.items()}
CONTACT_STATES = {f"contact_{name}": labels for name, labels in CONTACT_SENSORS.items()}
PRESENCE_STATE_COLUMNS = {f"presence_{name}": labels for name, labels in PRESENCE_STATES.items()}
PRESENCE_EVENT_COLUMNS = {f"presence_{name}": signal for name, signal in PRESENCE_EVENTS.items()}

# What build_master_timeline consumes. A new sensor type joins the master table by being
# appended here.
SENSOR_FAMILIES = [
    (VIBRATION_STATES, None),
    (MOTION_STATES, None),
    (CONTACT_STATES, None),
    (PRESENCE_STATE_COLUMNS, PRESENCE_EVENT_COLUMNS),
]

# Optional categorical summaries of a group of one-hot columns. The one-hot columns are
# kept alongside, so both views are available.
LABEL_COLUMNS = {
    "presence_zone": list(PRESENCE_STATE_COLUMNS),
}

# --------------------------------------------------------------------------------------
# Gap limits
# --------------------------------------------------------------------------------------

# How long a sensor may fall silent before its next signal counts as a new activity rather
# than a continuation of the current one.
DEFAULT_GAP_LIMIT_MINUTES = 2

# Per-sensor overrides, keyed by prefixed column name. Sensors absent here use the
# default. Set these from the sweep below plus what the participant reports: if someone
# says they ride once a day, the gap limit that yields about one activity per day is the
# defensible one.
GAP_LIMITS_MINUTES = {
    # "vib_bike": 2,
}

# Thresholds to sweep when checking how sensitive a sensor's activity count is to the gap
# limit. A count that keeps falling across the whole range has no natural session
# boundary; one that plateaus has, and the plateau is the defensible choice.
GAP_LIMIT_SWEEP_MINUTES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15]

# --------------------------------------------------------------------------------------
# Location estimation
# --------------------------------------------------------------------------------------

# Which room each signal implies a person is in: {signal: room}. Only signals carrying
# locational evidence need an entry; a signal with no entry never moves the estimate.
# Several zones of one presence sensor usually map to the same room.
SIGNAL_LOCATIONS = {
    # "In_Kitchen": "kitchen",
}

# Signals grouped by what they tell us about location.
#
# A signal is an *observation* of where someone was at an instant, not a state that stays
# true. The most recent observation therefore always wins; strength never lets an older
# signal outrank a newer one. This matters because sensors report departures late — a
# motion sensor may not send its off signal until a minute after the person left, by which
# time another sensor has already seen them elsewhere.
#
# So these tiers do not decide which of two signals wins. They decide whether a signal is
# an observation at all. The first LOCATION_POSITIVE_TIERS tiers are positive: an event
# saying a person was here, now. The rest are negative: a zone reporting itself vacated,
# which places nobody anywhere and can only falsify a current belief.
SIGNAL_PRIORITY = [
    # tier 0, positive: vibration "on", contact "on", motion "on" — something was moved
    [],
    # tier 1, positive: contact "off", presence events, presence state "on"
    [],
    # tier 2, negative: presence state "off"
    [],
    # tier 3, negative: vibration "off", motion "off" — a timeout, not an observation
    [],
]

# How many leading tiers count as positive evidence. Tiers from this index on only
# falsify. Note that splitting the positive tiers changes nothing about the output, since
# each row carries one signal and recency decides: keep the split for readability only.
LOCATION_POSITIVE_TIERS = 2

# How long an observation stays good before the estimate reverts to unknown. Without this
# the last signal before a silent night holds that room until morning. Check the gap
# distribution on a new export before choosing: if long silences are a large share of the
# span, "unknown" is the honest answer for most of them.
LOCATION_DECAY_MINUTES = 30

# How long a room gets to re-confirm itself after one of its zones reports being vacated.
# Where several zones share a room, a zone exit usually means the person moved within the
# room rather than out of it, and without a grace window the estimate flickers to unknown
# between every pair of zones. Set to None if each room has exactly one zone.
LOCATION_ZONE_EXIT_GRACE_SECONDS = 30
