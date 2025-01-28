import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
from mt5_funcs import *
from confg import *

class FVGState:
    """Class to track FVG state for each symbol"""
    def __init__(self):
        self.active = False
        self.type = None  # 1 for bullish, -1 for bearish
        self.upper_level = None
        self.lower_level = None
        self.activation_time = None
        self.current_order = None

# Global state
symbol_states = {symbol: FVGState() for symbol in SYMBOLS}

def detect_fvg(df):
    """Detect Fair Value Gap on higher timeframe"""
    try:
        # Calculate FVG levels
        df = calculate_fvg(df)
        
        # Check last candle for new FVG
        last_candle = df.iloc[-1]
        
        if last_candle['fvg'] == 0:
            return 0, None, None
            
        # FVG detected
        fvg_type = last_candle['fvg']
        upper_level = last_candle['U_fvg']
        lower_level = last_candle['L_fvg']
        
        
        return fvg_type, upper_level, lower_level
        
    except Exception as e:
        print(f"❌ Error in FVG detection: {e}")
        return 0, None, None

def calculate_fvg(df):
    """Calculate FVG levels using numpy vectorization"""
    df['fvg'] = np.where(
    (df['high'].shift(3) < df['low'].shift(1)) & 
    (df['low'] < df['low'].shift(1)) & 
    (df['low'] > df['high'].shift(3)), 1,
    np.where(
        (df['low'].shift(3) > df['high'].shift(1)) & 
        (df['high'] > df['high'].shift(1)) & 
        (df['high'] < df['low'].shift(3)), -1, 0
    )
)

    
    df['U_fvg'] = np.where(
        df['fvg'] == 1, df['low'].shift(1),
        np.where(df['fvg'] == -1, df['low'].shift(3), np.nan)
    )
    
    df['L_fvg'] = np.where(
        df['fvg'] == 1, df['high'].shift(3),
        np.where(df['fvg'] == -1, df['high'].shift(1), np.nan)
    )
    
    return df


def process_symbol(symbol):
    """Process single symbol"""
    try:
        state = symbol_states[symbol]
        if has_open_positions() : 
            for pair in SYMBOLS:
                cancel_all_orders(pair)
            state.active = False
        else:
            state = symbol_states[symbol]
            
            # Get current data
            df_high = get_bars(symbol, TIMEFRAME_HIGH, 10)
            df_low = get_bars(symbol, TIMEFRAME_LOW, 3)
            
            if df_high is None or df_low is None:
                print(f"❌ Error getting data for {symbol}")
                return
                
            # Check for FVG on higher timeframe
            fvg_type, upper_level, lower_level = detect_fvg(df_high)
            
            # If new FVG detected
            if fvg_type != 0 and not state.active:
                state.active = True
                state.type = fvg_type
                state.upper_level = upper_level
                state.lower_level = lower_level
                state.activation_time = datetime.now()
                

            
            # Process active FVG
            if state.active:
                current_price = mt5.symbol_info_tick(symbol)
                if current_price is None:
                    print(f"❌ Failed to get current price for {symbol}")
                    return
            
                            
                # Check invalidation
                if (state.type == 1 and current_price.bid <= state.lower_level) or \
                (state.type == -1 and current_price.ask >= state.upper_level):
                    cancel_all_orders(symbol)
                    state.active = False
                    print(f"❌ FVG invalidated for {symbol} - Price reached invalidation level")
                    return
                    
                # Check time expiration (one 10m candle)
                time_active = datetime.now() - state.activation_time
                
                if time_active > timedelta(minutes=9):
                    cancel_all_orders(symbol)
                    state.active = False
                    return
                    
                # Entry logic using last completed candle
                prev_high = df_low['high'].iloc[-2]  # Last completed candle
                prev_low = df_low['low'].iloc[-2]    # Last completed candle
                
            
                # Check existing orders first
                existing_orders = mt5.orders_get(symbol=symbol)
                
                if not existing_orders and state.current_order is not None:
                    print(f"🔄 Resetting order state for {symbol} as no orders exist")
                    state.current_order = None

                # Place or update order
                if state.current_order is None:

                    if state.type == 1:  # Bullish
                            tp = prev_high + (prev_high - prev_low) * TARGET_RR

                            order = place_order(
                                symbol=symbol,
                                order_type=mt5.ORDER_TYPE_BUY_STOP,
                                price=prev_high,
                                sl=prev_low,
                                tp=tp,
                                comment="FVG Long"
                            )
                            
                            if order:
                                state.current_order = order
                    
                    elif state.type == -1:  # Bearish
                            tp = prev_low - (prev_high - prev_low) * TARGET_RR
                            # Send_to_tele(f"""
                            # 🎯 Placing Sell Stop Order for {symbol}
                            # Entry: {prev_low}
                            # SL: {prev_high}
                            # TP: {tp}
                            # Current Price: {current_price.ask}
                            # Lower FVG: {state.lower_level}
                            # """)
                            
                            order = place_order(
                                symbol=symbol,
                                order_type=mt5.ORDER_TYPE_SELL_STOP,
                                price=prev_low,
                                sl=prev_high,
                                tp=tp,
                                comment="FVG Short"
                            )
                            
                            if order:
                                state.current_order = order
                
                else:
                    # Check if we need to update the order levels
                    current_orders = mt5.orders_get(symbol=symbol)
                    if current_orders and len(current_orders) > 0:
                        # Compare current order levels with new levels
                        order = current_orders[0]

                        # For bullish FVG
                        if state.type == 1 and (order.price_open != prev_high or order.sl != prev_low):
                            cancel_all_orders(symbol)
                            state.current_order = None
                            # Send_to_tele(f"🔄 Updating buy stop levels for {symbol}")
                        
                        # For bearish FVG
                        elif state.type == -1 and (order.price_open != prev_low or order.sl != prev_high):
                            cancel_all_orders(symbol)
                            state.current_order = None
                            # Send_to_tele(f"🔄 Updating sell stop levels for {symbol}")

    except Exception as e:
        print(f"❌ Error processing {symbol}: {e}")
        # Reset state on error
        state.active = False
        state.current_order = None
        
        
def main():
    """Main bot loop"""
    # Connect to MT5
    if not connect_mt5():
        print("Failed to connect to MT5")
        return
        
    print("FVG Bot started")
    
    while True:
        try:
            # Check trading hours
            if not check_trading_hours():
                # Close all positions and orders if outside trading hours
                for symbol in SYMBOLS:
                    close_position(symbol)
                    cancel_all_orders(symbol)
                time.sleep(60)
                continue
                
            # Check if we have any open positions
            if has_open_positions():
                time.sleep(1)
                continue
                
            # Process each symbol
            for symbol in SYMBOLS:
                process_symbol(symbol)
                time.sleep(0.1)  # Small delay between symbols
                
        except Exception as e:
            print(f"Main loop error: {e}")
            
            time.sleep(1)  # Main loop delay

if __name__ == "__main__":
    main()