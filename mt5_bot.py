import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta
import time
from mt5_funcs import *
from confg import *

# Global dictionary to track last processed time per symbol
last_processed = {symbol: None for symbol in SYMBOLS}

def detect_atr_signal(df, symbol):
    """Detect if candle meets ATR criteria"""
    try:
        # Calculate ATR
        df['ATR'] = df.ta.atr(length=ATR_PERIOD)
        current_candle = df.iloc[-2]  # Use completed candle
        atr_value = df['ATR'].iloc[-2]

        # Check candle size and direction
        candle_size = current_candle['high'] - current_candle['low']
        if candle_size < (ATR_MULTIPLIER * atr_value):
            return 0, None, None

        # Determine direction
        if current_candle['close'] > current_candle['open']:  # Bullish
            return 1, atr_value, current_candle['time']
        elif current_candle['close'] < current_candle['open']:  # Bearish
            return -1, atr_value, current_candle['time']
            
        return 0, None, None
    except Exception as e:
        print(f"ATR detection error for {symbol}: {e}")
        return 0, None, None

def process_symbol(symbol):
    """Process single symbol"""
    try:
        global last_processed
        
        # Check existing positions first
        if has_open_positions():
            return

        # Get price data (20 bars to calculate ATR 10 reliably)
        df = get_bars(symbol, TIMEFRAME, 20)
        if df is None or len(df) < 20:
            return

        # Check if we've already processed this candle
        current_candle_time = df.iloc[-2]['time']
        if last_processed[symbol] == current_candle_time:
            return

        # Detect ATR signal
        signal_type, atr_value, candle_time = detect_atr_signal(df, symbol)
        if signal_type == 0:
            return

        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            print(f"Price check failed for {symbol}")
            return

        # Calculate SL/TP levels
        if signal_type == 1:  # Bullish
            entry_price = tick.ask
            sl_price = entry_price - (1.5 * atr_value)
            tp_price = entry_price + (TARGET_RR * 1.5 * atr_value)
            order_type = mt5.ORDER_TYPE_BUY
        else:  # Bearish
            entry_price = tick.bid
            sl_price = entry_price + (1.5 * atr_value)
            tp_price = entry_price - (TARGET_RR * 1.5 * atr_value)
            order_type = mt5.ORDER_TYPE_SELL

        # Place market order
        order = place_order(
            symbol=symbol,
            order_type=order_type,
            price=entry_price,
            sl=sl_price,
            tp=tp_price,
            comment=f"ATR_{'Bull' if signal_type ==1 else 'Bear'}"
        )
        
        if order:
            last_processed[symbol] = candle_time
            print(f"Order placed for {symbol} at {entry_price}")

    except Exception as e:
        print(f"Error processing {symbol}: {e}")

def main():
    """Main bot loop"""
    if not connect_mt5():
        print("Failed to connect to MT5")
        return

    print("ATR Bot started")
    time.sleep(25200)
    while True:
        try:
            if not check_trading_hours():
                for symbol in SYMBOLS:
                    close_position(symbol)
                    cancel_all_orders(symbol)
                time.sleep(60)
                continue

            # Process each symbol
            for symbol in SYMBOLS:
                process_symbol(symbol)
                time.sleep(0.1)

            time.sleep(1)  # Check every second
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()