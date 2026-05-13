"""Finite state machine keys stored in `context.user_data` (per-user conversation state)."""

# Keys
STATE_KEY = "cp_fsm_state"
DATA_KEY = "cp_fsm_data"

# Dashboard / navigation
ST_DASHBOARD = "dashboard"

# Broadcast flow
ST_BC_WAIT_CONTENT = "bc_content"
ST_BC_BUTTONS_ASK = "bc_buttons_ask"
ST_BC_BUTTON_TEXT = "bc_btn_text"
ST_BC_BUTTON_URL = "bc_btn_url"
ST_BC_PREVIEW = "bc_preview"

# Scheduler flow
ST_SCH_WAIT_CONTENT = "sch_content"
ST_SCH_BUTTONS_ASK = "sch_buttons_ask"
ST_SCH_BUTTON_TEXT = "sch_btn_text"
ST_SCH_BUTTON_URL = "sch_btn_url"
ST_SCH_KIND = "sch_kind"
ST_SCH_TIME = "sch_time"
ST_SCH_WEEKDAY = "sch_weekday"
ST_SCH_INTERVAL = "sch_interval"
ST_SCH_TITLE = "sch_title"
ST_SCH_PREVIEW = "sch_preview"

# Settings
ST_SET_CHANNEL = "set_channel"
ST_SET_DISCUSSION = "set_discussion"
ST_SET_TZ = "set_tz"


def reset_fsm(user_data: dict) -> None:
    """Clear FSM state and scratch payload for a user."""
    user_data.pop(STATE_KEY, None)
    user_data.pop(DATA_KEY, None)
    user_data.pop("panel_chat_id", None)
    user_data.pop("panel_message_id", None)


def get_state(user_data: dict) -> str | None:
    return user_data.get(STATE_KEY)


def set_state(user_data: dict, state: str) -> None:
    user_data[STATE_KEY] = state


def get_data(user_data: dict) -> dict:
    """Mutable scratch dict for multi-step flows."""
    if DATA_KEY not in user_data:
        user_data[DATA_KEY] = {}
    return user_data[DATA_KEY]
