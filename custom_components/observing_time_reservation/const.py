"""Constants for the Observing Time Reservation integration."""
from __future__ import annotations

DOMAIN = "observing_time_reservation"

# --- config/options keys -----------------------------------------------
CONF_BACKEND = "backend"
# A telescope is rarely one HA device: INDI exposes the mount, CCD/camera,
# focuser, filter wheel, etc. as separate devices (one each), and Seestar
# exposes telephoto/wide cameras plus mount/health as one device but still
# alongside unrelated devices in the same HA instance. So this is a *list*
# of every HA device that belongs to this telescope, used only to narrow the
# entity pickers in the capability-mapping step to this telescope's own
# entities instead of every entity in the house.
CONF_SOURCE_DEVICE_IDS = "source_device_ids"
CONF_MIN_DURATION = "min_duration_minutes"
CONF_MAX_DURATION = "max_duration_minutes"
CONF_SLOT_STEP = "slot_step_minutes"
CONF_IMAGE_BASE_PATH = "image_base_path"
CONF_CAPTURE_INTERVAL = "capture_interval_seconds"
CONF_ADMIN_USER_IDS = "admin_user_ids"
CONF_CAPABILITY_MAP = "capability_map"

BACKEND_INDI = "indi"
BACKEND_SEESTAR = "seestar"
BACKEND_MANUAL = "manual"
BACKENDS = [BACKEND_INDI, BACKEND_SEESTAR, BACKEND_MANUAL]

DEFAULT_MIN_DURATION = 30
DEFAULT_MAX_DURATION = 240
DEFAULT_SLOT_STEP = 15
DEFAULT_IMAGE_BASE_PATH = "/config/observing_sessions"
DEFAULT_CAPTURE_INTERVAL = 30

# --- capability keys (abstract actions the card can request) -----------
CAP_SET_GOTO_RA = "set_goto_ra"
CAP_SET_GOTO_DEC = "set_goto_dec"
CAP_GOTO = "goto"
CAP_STOP_GOTO = "stop_goto"
CAP_PARK = "park"
CAP_UNPARK = "unpark"
CAP_SET_TRACKING = "set_tracking"
CAP_START_CAPTURE = "start_capture"
CAP_STOP_CAPTURE = "stop_capture"
CAP_SET_EXPOSURE = "set_exposure"
CAP_SET_FILTER = "set_filter"
CAP_SET_FOCUS = "set_focus"
CAP_SET_CCD_TEMPERATURE = "set_ccd_temperature"
# Session-lifecycle switch some backends require before ANY other command
# works at all (e.g. ha-seestar's "Controls enabled" - every command is
# silently refused while it's off). The coordinator arms it automatically
# when a reservation becomes active and disarms it when the session ends;
# it is not a manual control in the UI.
CAP_CONTROLS_ENABLED = "controls_enabled"
# A second, manually-toggled gate some backends require specifically for
# destructive power actions (park/startup/shutdown) - left to the client to
# arm deliberately, per the upstream backend's own safety guidance.
CAP_ALLOW_POWER_ACTIONS = "allow_power_actions"
CAP_STARTUP_SEQUENCE = "startup_sequence"
CAP_SHUTDOWN = "shutdown"
CAP_SET_DEW_HEATER = "set_dew_heater"

# Seestar-specific action capabilities (ha-seestar's CONTROL_ENTITIES) that
# have no INDI equivalent - hidden automatically whenever unmapped, same as
# every other capability.
CAP_SET_IMAGING_MODE = "set_imaging_mode"
CAP_START_LIVE_VIEW = "start_live_view"
CAP_START_MOSAIC = "start_mosaic"
CAP_START_SPECTRA = "start_spectra"
CAP_SET_GOTO_TARGET_LABEL = "set_goto_target_label"
CAP_SET_GAIN = "set_gain"
CAP_AUTO_FOCUS = "auto_focus"
CAP_SET_MAG_DECLINATION = "set_mag_declination"
CAP_SET_WIDE_CAMERA = "set_wide_camera"
CAP_RECORD_VIDEO = "record_video"
CAP_PLATE_SOLVE_LOOP = "plate_solve_loop"
CAP_RUN_PLAN = "run_plan"
CAP_PAUSE_PLAN = "pause_plan"
CAP_CONTINUE_PLAN = "continue_plan"
CAP_SKIP_TARGET = "skip_target"
CAP_RESET_PLAN_ITEM = "reset_plan_item"

# capabilities that are entity references rather than action targets
REF_LIVE_CAMERA = "live_camera_entity"
REF_PREVIEW_CAMERA = "preview_camera_entity"
REF_STATUS_SENSOR = "status_sensor_entity"

# Read-only telemetry references. These make the *current* state of the
# telescope visible in the panel (temperature, where it's actually pointing,
# stacking progress, ...) as opposed to the write-only setpoints above - a
# serious user needs both, not just buttons to push blind.
REF_TEMPERATURE = "temperature_sensor_entity"
REF_BATTERY = "battery_sensor_entity"
REF_CURRENT_RA = "current_ra_sensor_entity"
REF_CURRENT_DEC = "current_dec_sensor_entity"
REF_ALTITUDE = "altitude_sensor_entity"
REF_AZIMUTH = "azimuth_sensor_entity"
REF_TRACKING_STATE = "tracking_state_sensor_entity"
REF_SLEWING_STATE = "slewing_state_sensor_entity"
REF_AT_PARK = "at_park_sensor_entity"
REF_STACK_STATE = "stack_state_sensor_entity"
REF_STACKED_FRAMES = "stacked_frames_sensor_entity"
REF_DROPPED_FRAMES = "dropped_frames_sensor_entity"
REF_TOTAL_FRAMES = "total_frames_sensor_entity"
REF_INTEGRATION_TIME = "integration_time_sensor_entity"
REF_FOCUSER_POSITION = "focuser_position_sensor_entity"
REF_FILTER_POSITION = "filter_position_sensor_entity"

ACTION_CAPABILITIES = [
    CAP_SET_GOTO_RA,
    CAP_SET_GOTO_DEC,
    CAP_GOTO,
    CAP_STOP_GOTO,
    CAP_PARK,
    CAP_UNPARK,
    CAP_SET_TRACKING,
    CAP_START_CAPTURE,
    CAP_STOP_CAPTURE,
    CAP_SET_EXPOSURE,
    CAP_SET_FILTER,
    CAP_SET_FOCUS,
    CAP_SET_CCD_TEMPERATURE,
    CAP_CONTROLS_ENABLED,
    CAP_ALLOW_POWER_ACTIONS,
    CAP_STARTUP_SEQUENCE,
    CAP_SHUTDOWN,
    CAP_SET_DEW_HEATER,
    CAP_SET_IMAGING_MODE,
    CAP_START_LIVE_VIEW,
    CAP_START_MOSAIC,
    CAP_START_SPECTRA,
    CAP_SET_GOTO_TARGET_LABEL,
    CAP_SET_GAIN,
    CAP_AUTO_FOCUS,
    CAP_SET_MAG_DECLINATION,
    CAP_SET_WIDE_CAMERA,
    CAP_RECORD_VIDEO,
    CAP_PLATE_SOLVE_LOOP,
    CAP_RUN_PLAN,
    CAP_PAUSE_PLAN,
    CAP_CONTINUE_PLAN,
    CAP_SKIP_TARGET,
    CAP_RESET_PLAN_ITEM,
]

REFERENCE_CAPABILITIES = [
    REF_LIVE_CAMERA,
    REF_PREVIEW_CAMERA,
    REF_STATUS_SENSOR,
    REF_TEMPERATURE,
    REF_BATTERY,
    REF_CURRENT_RA,
    REF_CURRENT_DEC,
    REF_ALTITUDE,
    REF_AZIMUTH,
    REF_TRACKING_STATE,
    REF_SLEWING_STATE,
    REF_AT_PARK,
    REF_STACK_STATE,
    REF_STACKED_FRAMES,
    REF_DROPPED_FRAMES,
    REF_TOTAL_FRAMES,
    REF_INTEGRATION_TIME,
    REF_FOCUSER_POSITION,
    REF_FILTER_POSITION,
]

ALL_CAPABILITIES = ACTION_CAPABILITIES + REFERENCE_CAPABILITIES

# --- services ------------------------------------------------------------
SERVICE_RESERVE = "reserve"
SERVICE_CANCEL = "cancel_reservation"
SERVICE_SET_AVAILABILITY = "set_availability"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_SET_RECORDING = "set_recording"
SERVICE_SAVE_FRAME = "save_frame"
# Multi-exposure sequence (ordered capture steps - filter/exposure/count),
# modeled on CCDciel's own plan/step engine. See sequence.py.
SERVICE_START_SEQUENCE = "start_sequence"
SERVICE_PAUSE_SEQUENCE = "pause_sequence"
SERVICE_RESUME_SEQUENCE = "resume_sequence"
SERVICE_CANCEL_SEQUENCE = "cancel_sequence"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_START = "start"
ATTR_END = "end"
ATTR_RESERVATION_ID = "reservation_id"
ATTR_WINDOWS = "windows"
ATTR_CAPABILITY = "capability"
ATTR_VALUE = "value"
ATTR_ENABLED = "enabled"
ATTR_STEPS = "steps"

STORAGE_VERSION = 1
