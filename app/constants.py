from __future__ import annotations

# Symbol types
SYMBOL_TYPE_CRYPTO = "crypto"
SYMBOL_TYPE_STOCK = "stock"
SYMBOL_TYPES = {SYMBOL_TYPE_CRYPTO, SYMBOL_TYPE_STOCK}

# Timeframes
TIMEFRAME_15M = "15m"
TIMEFRAME_1H = "1h"
TIMEFRAME_1D = "1d"
TIMEFRAME_1W = "1w"
TIMEFRAME_1MO = "1mo"
TIMEFRAMES = (TIMEFRAME_15M, TIMEFRAME_1H, TIMEFRAME_1D, TIMEFRAME_1W, TIMEFRAME_1MO)

# Ticker modes
TICKER_MODE_QUOTES = "quotes"
TICKER_MODE_NEWS = "news"
TICKER_MODE_CALENDAR = "calendar"

# Stream status
STATUS_STREAMING = "STREAMING"
STATUS_RECONNECTING = "RECONNECTING"
STATUS_STOCKS_ONLY = "STOCKS ONLY"
STATUS_CONNECTING = "CONNECTING"

# Common sentinel values
AGE_NOW = "now"
VALUE_NEVER = "never"

# Command mode tokens
CMD_Q = "q"
CMD_R = "r"
CMD_N = "n"
CMD_C = "c"
CMD_CALENDAR = "calendar"
CMD_HELP = "?"
CMD_ADD = "add"
CMD_DEL = "del"
CMD_MV = "mv"
CMD_EDIT = "edit"
COMMAND_TOKENS = (CMD_Q, CMD_R, CMD_N, CMD_C, CMD_CALENDAR, CMD_HELP, CMD_ADD, CMD_DEL, CMD_MV, CMD_EDIT)

# UI selectors (Textual IDs)
ID_HEADER = "#header"
ID_STATUS_LINE = "#status_line"
ID_TICKER = "#ticker"
ID_EVENTS = "#events"
ID_COMMAND_INPUT = "#command_input"
ID_NEWS_HEADER = "#news_header"
ID_NEWS_TABLE = "#news_table"
ID_MAIN_TABLE = "#crypto_quotes"
ID_ALERTS_TABLE = "#stock_quotes"
ID_INDICATORS_TABLE = "#indicators_table"

# Rotation table IDs
ROTATE_MAIN = "crypto_quotes"
ROTATE_NEWS = "news_table"
ROTATE_INDICATORS = "indicators_table"
