"""Constants for the Observing Time Reservation integration."""
from __future__ import annotations

DOMAIN = "observing_time_reservation"

# --- config/options keys -----------------------------------------------
CONF_BACKEND = "backend"
CONF_SOURCE_DEVICE_ID = "source_device_id"
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

# capabilities that are entity references rather than action targets
REF_LIVE_CAMERA = "live_camera_entity"
REF_PREVIEW_CAMERA = "preview_camera_entity"
REF_STATUS_SENSOR = "status_sensor_entity"

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
]

REFERENCE_CAPABILITIES = [
    REF_LIVE_CAMERA,
    REF_PREVIEW_CAMERA,
    REF_STATUS_SENSOR,
]

ALL_CAPABILITIES = ACTION_CAPABILITIES + REFERENCE_CAPABILITIES

# --- services ------------------------------------------------------------
SERVICE_RESERVE = "reserve"
SERVICE_CANCEL = "cancel_reservation"
SERVICE_SET_AVAILABILITY = "set_availability"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_SET_RECORDING = "set_recording"
SERVICE_SAVE_FRAME = "save_frame"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_START = "start"
ATTR_END = "end"
ATTR_RESERVATION_ID = "reservation_id"
ATTR_WINDOWS = "windows"
ATTR_CAPABILITY = "capability"
ATTR_VALUE = "value"
ATTR_ENABLED = "enabled"

STORAGE_VERSION = 1
