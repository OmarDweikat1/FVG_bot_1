import MetaTrader5 as mt5

# Configuration
SYMBOLS = ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD', 'XAUUSD', 'GBPCAD']
RISK_AMOUNT = 10       # Base risk amount
TARGET_RR = 3          # Risk:Reward ratio
ATR_PERIOD = 10        # ATR period
ATR_MULTIPLIER = 2     # Candle size multiplier
TIMEFRAME = mt5.TIMEFRAME_M10  # Main timeframe for signal detection
