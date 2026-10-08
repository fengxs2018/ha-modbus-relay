"""Constants for the Modbus RTU multi-channel relay integration."""

DOMAIN = "modbus_relay"

MANUFACTURER = "中盛科技 (ZhongSheng)"

CONF_SLAVE = "slave"
CONF_CHANNELS = "channels"
CONF_READ_STATE = "read_state"

DEFAULT_NAME = "多路继电器"
DEFAULT_HOST = "192.168.100.254"
DEFAULT_PORT = 23
DEFAULT_SLAVE = 1
DEFAULT_CHANNELS = 16
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_TIMEOUT = 5

MIN_CHANNELS = 1
MAX_CHANNELS = 72

# 0 means "do not poll, use optimistic state"
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 600
