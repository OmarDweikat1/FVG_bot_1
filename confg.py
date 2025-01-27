import MetaTrader5 as mt5

# Configuration
SYMBOLS = ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD',
        'GBPJPY', 'EURJPY', 'AUDJPY',
        'EURGBP', 'GBPCAD',
        'XAUUSD']

RISK_AMOUNT = 10  # Fixed $10 risk
TARGET_RR = 3     # Risk:Reward ratio
TIMEFRAME_HIGH = mt5.TIMEFRAME_M10
TIMEFRAME_LOW = mt5.TIMEFRAME_M5