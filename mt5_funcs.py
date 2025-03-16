import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time, requests
from confg import SYMBOLS
import random
import pytz
import pandas_ta as ta

def connect_mt5():
    try:
        if not mt5.initialize():
            print("❌ MT5 initialization failed")
            return False
        
        account_info = mt5.account_info()
        if account_info is None:
            print("❌ Failed to get account info")
            return False
            
        print(f"""
		✅ MT5 Connected Successfully
		Balance: ${account_info.balance}
		Equity: ${account_info.equity}
		""")
        return True
    except Exception as e:
        print(f"❌ MT5 initialization error: {e}")
        return False

def get_bars(symbol, timeframe, n_bars):
    """Get n_bars of data for symbol and timeframe"""
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
        if rates is None:
            print(f"❌ Failed to get bars for {symbol}")
            return None
        return pd.DataFrame(rates)
    except Exception as e:
        print(f"❌ Error getting bars for {symbol}: {e}")
        return None

def calculate_global_loss_streak():
    """
    Calculate current loss streak and cumulative loss across all symbols.
    Returns loss streak count and total loss amount.
    """
    try:
        # Get trading history for last 30 days
        today = datetime.now() + timedelta(days=1)
        past_date = today - timedelta(days=30)
        trades = mt5.history_deals_get(past_date, today)
        
        if trades is None or len(trades) == 0:
            print("No trading history found - Using base risk")
            return 1, 0
            
        trades_df = pd.DataFrame(list(trades), columns=trades[0]._asdict().keys())
        trades_df['time'] = pd.to_datetime(trades_df['time'], unit='s')
        trades_df = trades_df.sort_values('time', ascending=False)
        
        position_trades = trades_df.groupby(['position_id']).agg({
            'profit': 'sum',
            'symbol': 'first',
            'time': 'max',
            'volume': 'max',
            'entry': 'first'
        }).reset_index()
        position_trades = position_trades.sort_values('time', ascending=False)
        
        loss_streak = 0
        cumulative_loss = 0
        for _, trade in position_trades.iterrows():
            profit = trade['profit']
            if profit < 2:
                loss_streak += 1
                cumulative_loss += abs(profit)
                if loss_streak >= 10:
                    loss_streak = 0 
                    cumulative_loss = 0
            else:
                break
        loss_streak = max(1, loss_streak)
        return loss_streak, cumulative_loss
        
    except Exception as e:
        print(f"Error calculating loss streak: {str(e)}")
        return 1, 0

def calculate_risk_amount(loss_streak, cumulative_loss):
    """Calculate risk amount based on loss streak and cumulative loss"""
    try:
        if loss_streak <= 1:
            return 10.0
        risk = (((loss_streak + 1) * 10) + cumulative_loss) / 3
        print(f"""
		💰 Risk Calculation:
		Formula: (((loss_streak + 1) * 10) + cumulative_loss) / 3
		Values:
		- Loss Streak: {loss_streak}
		- Loss Streak + 1: {loss_streak + 1}
		- Base Amount: ${(loss_streak + 1) * 10:.2f}
		- Cumulative Loss: ${cumulative_loss:.2f}
		- Total Before Division: ${((loss_streak + 1) * 10) + cumulative_loss:.2f}
		Final Risk Amount: ${risk:.2f}
		""")
        return round(risk, 2)
    except Exception as e:
        print(f"⚠️ Error in risk calculation: {str(e)}")
        return 10.0

def calculate_lot_size(risk_amount, stop_loss_value, symbol):
    """
    Calculate lot size based on risk amount and stop loss value.
    
    For XAUUSD:
      - stop_loss_value is in dollars (price difference).
      - raw_lot_size = risk_amount / (stop_loss_value * contract_size)
      - Adjust for the broker's tick value using:
            tick_value_ratio = broker_tick_value / default_tick_value
      - Final lot size is rounded to the allowed volume step.
    
    For other symbols:
      - stop_loss_value is in points.
    """
    try:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise ValueError(f"Symbol {symbol} not found")
        
        if symbol == 'XAUUSD':
            contract_size = symbol_info.trade_contract_size  # e.g., 100
            # Here, stop_loss_value is the dollar difference (e.g., $50)
            raw_lot_size = risk_amount / (stop_loss_value * contract_size)
            
            point_value = symbol_info.trade_tick_value
            default_info = mt5.symbol_info("XAUUSD")
            default_tick_value = default_info.trade_tick_value if default_info else 0.1
            tick_value_ratio = point_value / default_tick_value if default_tick_value != 0 else 1
            raw_lot_size /= tick_value_ratio
        else:
            # For other symbols, stop_loss_value is given in points.
            point_value = symbol_info.trade_tick_value
            sl_dollars = stop_loss_value * point_value
            raw_lot_size = risk_amount / sl_dollars if sl_dollars != 0 else 0.01

        # Round raw lot size to nearest allowed step
        lot_size = np.round(raw_lot_size * 100) / 100
        final_lot_size = max(symbol_info.volume_min, min(lot_size, symbol_info.volume_max))
        # Calculate actual risk for logging (for XAUUSD, multiplier is contract_size)
        if symbol == 'XAUUSD':
            actual_risk = final_lot_size * stop_loss_value * contract_size
        else:
            actual_risk = final_lot_size * sl_dollars

        print(f"Calculated raw lot size: {raw_lot_size}")
        print(f"Allowed lot range: {symbol_info.volume_min} - {symbol_info.volume_max}")
        print(f"Lot step: {symbol_info.volume_step}")
        print(f"Final lot size after rounding: {final_lot_size}\n")
        
        return final_lot_size, actual_risk

    except Exception as e:
        return 0.01, risk_amount

def check_trading_capabilities(symbol):
    """Check specific trading capabilities for a symbol"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Symbol {symbol} not found")
        return False
        
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print(f"❌ Symbol {symbol} selection failed")
            return False
    return True

def place_order(symbol, order_type, price, sl, tp, comment=""):
    """Place market order with risk management"""
    try:
        if not check_trading_capabilities(symbol):
            return None

        # Determine order action and price
        if order_type in [mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL]:
            action = mt5.TRADE_ACTION_DEAL
            tick = mt5.symbol_info_tick(symbol)
            price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        else:
            action = mt5.TRADE_ACTION_PENDING

        # Risk management calculations
        loss_streak, cumulative_loss = calculate_global_loss_streak()
        risk_amount = calculate_risk_amount(loss_streak, cumulative_loss)
        
        symbol_info = mt5.symbol_info(symbol)
        # For XAUUSD, use the dollar difference directly.
        if symbol == 'XAUUSD':
            stop_loss_value = abs(price - sl)  # dollars difference (e.g., $50)
        else:
            # For other symbols, calculate stop loss in points.
            stop_loss_value = abs(price - sl) / symbol_info.point
        
        lot_size, actual_risk = calculate_lot_size(risk_amount, stop_loss_value, symbol)

        request = {
            "action": action,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 234000,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order failed: {result.comment}")
            return None
            
        return result.order
    except Exception as e:
        print(f"Order error: {e}")
        return None

def validate_order_parameters(symbol, price, sl, tp):
    """Validate order parameters against symbol specifications"""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Failed to get symbol info for {symbol}")
        return False
        
    tick_size = symbol_info.trade_tick_size
    if tick_size > 0:
        price = round(price / tick_size) * tick_size
        sl = round(sl / tick_size) * tick_size
        tp = round(tp / tick_size) * tick_size
            
    return price, sl, tp

def cancel_all_orders(symbol=None):
    """Cancel all pending orders for a symbol or all symbols"""
    try:
        orders = mt5.orders_get(symbol=symbol)
        if orders is None:
            return True
        
        for order in orders:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Failed to cancel order {order.ticket}: {result.comment}")
                return False
                
            print(f"✅ Order {order.ticket} cancelled successfully")
        return True
    except Exception as e:
        print(f"❌ Error cancelling orders: {e}")
        return False

def close_position(symbol):
    """Close open position for symbol"""
    try:
        position = mt5.positions_get(symbol=symbol)
        if position is None or len(position) == 0:
            return True
            
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"❌ Failed to get tick data for {symbol}")
            return False
            
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": position[0].volume,
            "type": mt5.ORDER_TYPE_BUY if position[0].type == 1 else mt5.ORDER_TYPE_SELL,
            "position": position[0].ticket,
            "price": tick.ask if position[0].type == 1 else tick.bid,
            "deviation": 20,
            "magic": 234000,
            "comment": "Close position",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        print(f"""
		🔄 Closing Position:
		Symbol: {symbol}
		Ticket: {position[0].ticket}
		Volume: {position[0].volume}
		Type: {'SELL' if position[0].type == 1 else 'BUY'}
		""")
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Failed to close position: {result.comment}")
            return False
            
        print(f"✅ Position closed successfully")
        return True
    except Exception as e:
        print(f"❌ Error closing position: {e}")
        return False

def check_trading_hours():
    """Check if current time is within trading hours (02:00-15:00 NY time)"""
    ny_tz = pytz.timezone('America/New_York')
    current_time = datetime.now(pytz.UTC).astimezone(ny_tz).time()
    is_trading_time = current_time >= datetime.strptime("02:00", "%H:%M").time() and \
                      current_time <= datetime.strptime("15:00", "%H:%M").time()
    if not is_trading_time:
        print("⏰ Outside trading hours")
        time.sleep(600)
    return is_trading_time

def has_open_positions():
    """Check if there are any open positions and cancel pending orders if found"""
    try:
        positions = mt5.positions_get()
        if positions is None:
            return False
            
        position_count = len(positions)
        
        if position_count > 0:
            if position_count > 1:
                print(f"⚠️ Multiple positions detected ({position_count}). Closing one random position...")
                position_to_close = random.choice(positions)
                close_position(position_to_close.symbol)
            
            for symbol in SYMBOLS:
                orders = mt5.orders_get(symbol=symbol)
                if orders:
                    print(f"🔄 Cancelling pending orders for {symbol}")
                    cancel_all_orders(symbol)
        return position_count > 0
        
    except Exception as e:
        print(f"❌ Error checking positions: {e}")
        return True

def Send_to_tele(info, CHANNEL_TOKEN=['-1001808452700','-1001860330864'], 
                 TELEGRAM_TOKEN='5155203386:AAELx_sq7U24fB7fQ5Tz6pdvfCHl7n1qnBk'):
    try:
        info = f'{info}'
        for user in CHANNEL_TOKEN:
            payload2 = {
                'chat_id': user,
                'text': info,
                'parse_mode': 'HTML'
            }
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data=payload2
            ).content
    except Exception as e:
        print(f"Telegram Error: {e}")
