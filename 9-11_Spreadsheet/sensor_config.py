"""Label definitions for the HomeIntellex-2 export.

Separate from sensor_tools so a different export can supply its own labels without
touching the logic. Signal spellings below are copied from the data, including its
inconsistent separators: the bedroom computer uses hyphens, the office one underscores.
"""

SENSOR_TYPE_FIXES = {"Onvis_MotioinSensor": "Onvis_MotionSensor"}

# The microwave signal was renamed partway through 2026-09-06: "-Open" and "-Vib" both
# appear only in the first 18 minutes of logging and each is followed by a "-NoVib",
# exactly as "-O/C" is afterwards. Collapsing them gives clean alternation across all rows.
SIGNAL_TYPE_FIXES = {
    "MicrowaveDoor-Open": "MicrowaveDoor-O/C",
    "MicrowaveDoor-Vib": "MicrowaveDoor-O/C",
}

# on fires when activity starts, off when it stops
VIBRATION_SENSORS = {
    "bike": {"on": "Bike-InUse", "off": "Bike-Stopped"},
    "bedroom_computer": {"on": "On-Bedroom-Computer", "off": "Left-Bedroom-Computer"},
    "office_computer": {"on": "On_Office_Computer", "off": "Left_Office_Computer"},
    "microwave": {"on": "MicrowaveDoor-O/C", "off": "MicrowaveDoor-NoVib"},
}

MOTION_SENSORS = {
    "kitchen": {"on": "In_Kitchen", "off": "Left_Kitchen"},
    "office": {"on": "In_Office", "off": "Left_Office"},
    "bedroom": {"on": "In_Bedroom", "off": "Left_Bedroom"},
}

CONTACT_SENSORS = {
    "fridge_door": {"on": "FridgeDoor_Open", "off": "FridgeDoor_Close"},
    "garage_entrance": {"on": "GarageEntrance_Open", "off": "GarageEntrance_Close"},
}

# Presence_FP2 covers several independent zones in one export, so these are grouped by
# zone rather than by sensor_type. Livingroom has three signals and BedroomDoor has one.
PRESENCE_ZONES = {
    "sofa": ["Sofa-Sit", "Sofa-Left"],
    "tableside": ["TableSide-In", "TableSide-Out"],
    "chair": ["Chair-Sit", "Chair-Left"],
    "tvzone": ["TVzone-In", "TVzone-Out"],
    "bikeside": ["BikeSide-In", "BikeSide-Out"],
    "backyard": ["Backyard-In", "Backyard-Out"],
    "livingroom": ["Livingroom-In/out", "Livingroom-Occupied", "Livingroom-Vacant"],
    "bedroom_door": ["BedroomDoor"],
}

# Zones whose signals form a sustained on/off state: the column holds 1 from the on signal
# until the off signal arrives. Livingroom-Occupied/Vacant alternate cleanly, so the pair
# is treated as a state and the momentary In/out signal is tracked separately below.
PRESENCE_STATES = {
    "sofa": {"on": "Sofa-Sit", "off": "Sofa-Left"},
    "tableside": {"on": "TableSide-In", "off": "TableSide-Out"},
    "chair": {"on": "Chair-Sit", "off": "Chair-Left"},
    "tvzone": {"on": "TVzone-In", "off": "TVzone-Out"},
    "bikeside": {"on": "BikeSide-In", "off": "BikeSide-Out"},
    "backyard": {"on": "Backyard-In", "off": "Backyard-Out"},
    "livingroom": {"on": "Livingroom-Occupied", "off": "Livingroom-Vacant"},
}

# Signals that fire as an instant rather than a state, so there is no off signal to wait
# for. Their column is 1 only on the row where the signal occurred.
PRESENCE_EVENTS = {
    "livingroom_inout": "Livingroom-In/out",
    "bedroom_door": "BedroomDoor",
}

# Every sensor family as (states, events), consumed by build_master_timeline. A new sensor
# type joins the master table by being appended here. Column names are prefixed by family
# where a bare name would collide: motion "bedroom" vs presence "bedroom_door" are distinct,
# but the prefixes keep the master table readable about which sensor a column came from.
VIBRATION_STATES = {f"vib_{name}": labels for name, labels in VIBRATION_SENSORS.items()}
MOTION_STATES = {f"motion_{name}": labels for name, labels in MOTION_SENSORS.items()}
CONTACT_STATES = {f"contact_{name}": labels for name, labels in CONTACT_SENSORS.items()}
PRESENCE_STATE_COLUMNS = {f"presence_{name}": labels for name, labels in PRESENCE_STATES.items()}
PRESENCE_EVENT_COLUMNS = {f"presence_{name}": signal for name, signal in PRESENCE_EVENTS.items()}

SENSOR_FAMILIES = [
    (VIBRATION_STATES, None),
    (MOTION_STATES, None),
    (CONTACT_STATES, None),
    (PRESENCE_STATE_COLUMNS, PRESENCE_EVENT_COLUMNS),
]

# Optional categorical summaries of a group of one-hot columns, passed to
# build_master_timeline as `label_columns`. The one-hot columns are kept alongside.
LABEL_COLUMNS = {
    "presence_zone": list(PRESENCE_STATE_COLUMNS),
}

# --------------------------------------------------------------------------------------
# Gap limits
# --------------------------------------------------------------------------------------

# How long a sensor may fall silent before its next signal counts as a new activity rather
# than a continuation. A bike stopped at a light has not finished its ride; a fridge door
# closed for the same 90 seconds almost certainly has.
DEFAULT_GAP_LIMIT_MINUTES = 2

GAP_LIMITS_MINUTES = {
    "vib_bike": 2,
    "vib_bedroom_computer": 2,
    "vib_office_computer": 2,
    "vib_microwave": 2,
    "motion_kitchen": 2,
    "motion_office": 2,
    "motion_bedroom": 2,
}

# Thresholds to sweep when checking how sensitive a sensor's activity count is to the
# gap limit. A count that keeps falling across the whole range has no natural session
# boundary; one that plateaus early does, and the plateau is the defensible choice.
GAP_LIMIT_SWEEP_MINUTES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 15]

# --------------------------------------------------------------------------------------
# Location estimation
# --------------------------------------------------------------------------------------

# Which room each signal implies a person is in. Only signals that carry locational
# evidence appear here; a signal with no entry never moves the estimate.
SIGNAL_LOCATIONS = {
    # vibration
    "Bike-InUse": "livingroom", "Bike-Stopped": "livingroom",
    "On-Bedroom-Computer": "bedroom", "Left-Bedroom-Computer": "bedroom",
    "On_Office_Computer": "office", "Left_Office_Computer": "office",
    "MicrowaveDoor-O/C": "kitchen", "MicrowaveDoor-NoVib": "kitchen",
    # motion
    "In_Kitchen": "kitchen", "Left_Kitchen": "kitchen",
    "In_Office": "office", "Left_Office": "office",
    "In_Bedroom": "bedroom", "Left_Bedroom": "bedroom",
    # contact
    "FridgeDoor_Open": "kitchen", "FridgeDoor_Close": "kitchen",
    "GarageEntrance_Open": "garage", "GarageEntrance_Close": "garage",
    # presence zones
    "Sofa-Sit": "livingroom", "Sofa-Left": "livingroom",
    "TableSide-In": "livingroom", "TableSide-Out": "livingroom",
    "Chair-Sit": "livingroom", "Chair-Left": "livingroom",
    "TVzone-In": "livingroom", "TVzone-Out": "livingroom",
    "BikeSide-In": "livingroom", "BikeSide-Out": "livingroom",
    "Backyard-In": "backyard", "Backyard-Out": "backyard",
    "Livingroom-Occupied": "livingroom", "Livingroom-Vacant": "livingroom",
    "Livingroom-In/out": "livingroom",
    "BedroomDoor": "bedroom",
}

# Signals grouped by what they tell us about location. Order is by strength of evidence,
# but strength does NOT decide which of two signals wins: a signal is an observation of
# where someone was at an instant, so the most recent one always wins. What these tiers
# decide is whether a signal is an observation at all.
#
# Tiers 0 and 1 are positive: an event that says a person was here, now. Both are "signal
# events" in the same sense, which is why they behave identically and the split is kept
# only for readability. Tiers 2 and 3 are negative: they report a room being vacated, so
# they cannot place anyone anywhere. They only falsify a current belief.
#
# The distinction rests on what each signal can be caused by. A vibration or contact "on"
# needs someone to physically move an object; a motion "on" needs something to move, which
# is nearly always a person. An "off" fires on a timeout, so it says only that nothing has
# happened recently — equally true of every room the person is not in.
SIGNAL_PRIORITY = [
    # tier 0, positive: someone physically did this
    ["Bike-InUse", "On-Bedroom-Computer", "On_Office_Computer", "MicrowaveDoor-O/C",
     "FridgeDoor_Open", "GarageEntrance_Open",
     "In_Kitchen", "In_Office", "In_Bedroom"],
    # tier 1, positive: a presence report or a door, very likely a person
    ["FridgeDoor_Close", "GarageEntrance_Close",
     "Livingroom-In/out", "BedroomDoor",
     "Sofa-Sit", "TableSide-In", "Chair-Sit", "TVzone-In", "BikeSide-In",
     "Backyard-In", "Livingroom-Occupied"],
    # tier 2, negative: a presence zone reporting itself vacated
    ["Sofa-Left", "TableSide-Out", "Chair-Left", "TVzone-Out", "BikeSide-Out",
     "Backyard-Out", "Livingroom-Vacant"],
    # tier 3, negative: a timeout, not an observation of anything
    ["Bike-Stopped", "Left-Bedroom-Computer", "Left_Office_Computer",
     "MicrowaveDoor-NoVib", "Left_Kitchen", "Left_Office", "Left_Bedroom"],
]

# How many leading tiers count as positive evidence. Tiers at or past this index only
# falsify: they clear the estimate when they name the room currently believed occupied.
LOCATION_POSITIVE_TIERS = 2

# How long an observation stays good before the estimate reverts to unknown. Without this
# the last signal before a silent night holds that room until morning, and long silences
# dominate: gaps over an hour are 50% of this export's span. Nobody's location is known
# during those, and "unknown" is the honest answer.
LOCATION_DECAY_MINUTES = 30

# How long a room gets to re-confirm itself after one of its zones reports being vacated.
# Rooms here hold several zones, so a zone exit usually means the person moved within the
# room rather than out of it: 1544 of 1680 vacancy-driven unknowns in this export were
# resolved by the same room, at a median of 7 seconds. Without a grace window the estimate
# flickers to unknown between every pair of zones.
LOCATION_ZONE_EXIT_GRACE_SECONDS = 30
