import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time , requests
from confg import SYMBOLS
import random
import pytz



def connect_mt5():
	try:
		if not mt5.initialize():
			Send_to_tele("❌ MT5 initialization failed")
			return False
		
		account_info = mt5.account_info()
		if account_info is None:
			Send_to_tele("❌ Failed to get account info")
			return False
			
		Send_to_tele(f"""
		✅ MT5 Connected Successfully
		Balance: ${account_info.balance}
		Equity: ${account_info.equity}
		""")
		return True
	except Exception as e:
		Send_to_tele(f"❌ MT5 initialization error: {e}")
		return False

def get_bars(symbol, timeframe, n_bars):
	"""Get n_bars of data for symbol and timeframe"""
	try:
		rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
		if rates is None:
			Send_to_tele(f"❌ Failed to get bars for {symbol}")
			return None
		return pd.DataFrame(rates)
	except Exception as e:
		Send_to_tele(f"❌ Error getting bars for {symbol}: {e}")
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
			Send_to_tele("No trading history found - Using base risk")
			return 1, 0
			
		# Convert trades to DataFrame
		trades_df = pd.DataFrame(list(trades), columns=trades[0]._asdict().keys())
		
		# Basic data preparation
		trades_df['time'] = pd.to_datetime(trades_df['time'], unit='s')
		
		# Sort by time descending (newest first)
		trades_df = trades_df.sort_values('time', ascending=False)
		
		# First, let's see all trades before processing
		Send_to_tele("Raw trades before processing:")
		for _, trade in trades_df.head(10).iterrows():
			Send_to_tele(f"Time: {trade['time']}, Symbol: {trade['symbol']}, Profit: {trade['profit']}, Position: {trade['position_id']}")
		
		# Group by position ID and deal entry/exit
		position_trades = trades_df.groupby(['position_id']).agg({
			'profit': 'sum',
			'symbol': 'first',
			'time': 'max',
			'volume': 'max',
			'entry': 'first'  # Added entry field to help identify trade type
		}).reset_index()
		
		# Sort positions by time (newest first)
		position_trades = position_trades.sort_values('time', ascending=False)
		
		# Initialize streak counting
		loss_streak = 0
		cumulative_loss = 0
		trade_log = []
		print(position_trades)
		# Log full trade sequence
		for _, trade in position_trades.iterrows():
			profit = trade['profit']
			trade_info = (f"{trade['time'].strftime('%H:%M:%S')} - "
						 f"{'Loss' if profit < 0 else 'Win'}: ${profit:.2f} "
						 f"({trade['symbol']} {trade['volume']})")
			trade_log.append(trade_info)
			
			if profit < 2:
				loss_streak += 1
				cumulative_loss += abs(profit)
			else:
				break  # Stop counting at first profitable trade
				
		# Ensure minimum streak of 1 to get base risk
		loss_streak = max(1, loss_streak)
		
		# Log analysis results with full detail
		Send_to_tele(f"""
🔍 Loss Streak Analysis:
Recent trades (newest first):
{chr(10).join(trade_log)}

Current Streak: {loss_streak} losses
Total Loss: ${cumulative_loss:.2f}
Trades Analyzed: {len(position_trades)}
		""")
		
		return loss_streak, cumulative_loss
		
	except Exception as e:
		Send_to_tele(f"Error calculating loss streak: {str(e)}\n{e.format_exc()}")
		return 1, 0  # Return base values on error

def calculate_risk_amount(loss_streak, cumulative_loss):
	"""Calculate risk amount based on loss streak and cumulative loss"""
	try:
		if loss_streak <= 1:

			return 10.0
		
		#Formula: (((loss_streak + 1) * 10) + cumulative_loss) / 3
		risk = (((loss_streak + 1) * 10) + cumulative_loss) / 3
		
		Send_to_tele(f"""
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
		Send_to_tele(f"⚠️ Error in risk calculation: {str(e)}")
		return 10.0

def calculate_lot_size(risk_amount, stop_loss_points, symbol):
    """Calculate lot size based on risk amount and stop loss points"""
    try:
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise ValueError(f"Symbol {symbol} not found")
            
        
        # Special handling for XAUUSD
        if symbol == 'XAUUSD':
            point_value = symbol_info.trade_tick_value
            # Adjust calculation for gold's specific characteristics
            sl_dollars = stop_loss_points * point_value
            lot_size = risk_amount / sl_dollars if sl_dollars != 0 else 0.01
            lot_size = lot_size / 10
        # Handle cross pairs like EURGBP
        elif not symbol.endswith('USD'):
            try:
                # For cross pairs, calculate proper conversion
                base_currency = symbol[:3]
                counter_currency = symbol[3:]
                
                # Get conversion rates to USD
                if counter_currency != 'USD':
                    counter_usd_pair = f"{counter_currency}USD"
                    if mt5.symbol_info(counter_usd_pair) is not None:
                        counter_usd_rate = mt5.symbol_info_tick(counter_usd_pair).ask
                    else:
                        counter_usd_rate = 1.0
                else:
                    counter_usd_rate = 1.0
                    
                point_value = symbol_info.trade_tick_value * counter_usd_rate
                sl_dollars = stop_loss_points * point_value
                lot_size = risk_amount / sl_dollars if sl_dollars != 0 else 0.01
                
            except Exception as e:
                print(f"Error in cross pair calculation: {str(e)}")
                point_value = symbol_info.trade_tick_value
                sl_dollars = stop_loss_points * point_value
                lot_size = risk_amount / sl_dollars if sl_dollars != 0 else 0.01
        else:
            # Standard USD pairs
            point_value = symbol_info.trade_tick_value
            sl_dollars = stop_loss_points * point_value
            lot_size = risk_amount / sl_dollars if sl_dollars != 0 else 0.01
        if symbol == 'EURGBP':
            lot_size = lot_size * 100 / 80
        
        # Round to nearest 0.01 lot
        lot_size = np.round(lot_size * 100) / 100
        
        # Ensure within symbol limits
        final_lot_size = max(symbol_info.volume_min, min(lot_size, symbol_info.volume_max))
        
        # Calculate actual risk
        actual_risk = final_lot_size * sl_dollars

        return final_lot_size, actual_risk

    except Exception as e:
        return 0.01, risk_amount

def place_order(symbol, order_type, price, sl, tp, comment=""):
	"""Place trading order with automatic risk calculation"""
	try:
		Send_to_tele(f"""
		🔄 Starting Order Placement:
		Symbol: {symbol}
		Entry: {price}
		Stop Loss: {sl}
		Take Profit: {tp}
		""")
		
		loss_streak, cumulative_loss = calculate_global_loss_streak()
		risk_amount = calculate_risk_amount(loss_streak, cumulative_loss)
		
		sl_pips = abs(price - sl) / mt5.symbol_info(symbol).point
		Send_to_tele(f"📏 Stop Loss Distance: {sl_pips} points")
		
		lot_size = calculate_lot_size(risk_amount, sl_pips, symbol)
		
		request = {
			"action": mt5.TRADE_ACTION_PENDING,
			"symbol": symbol,
			"volume": lot_size,
			"type": order_type,
			"price": price,
			"sl": sl,
			"tp": tp,
			"deviation": 20,
			"magic": 234000,
			"comment": f"{comment} Risk=${risk_amount}",
			"type_time": mt5.ORDER_TIME_GTC,
			"type_filling": mt5.ORDER_FILLING_IOC,
		}
		

		
		result = mt5.order_send(request)
		
		if result.retcode != mt5.TRADE_RETCODE_DONE:
			Send_to_tele(f"❌ Order placement failed: {result.comment}")
			return None
			
		Send_to_tele(f"✅ Order placed successfully. Ticket: {result.order}")
		return result.order
		
	except Exception as e:
		Send_to_tele(f"❌ Error placing order: {e}")
		return None
	
	
	
	
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
			Send_to_tele(f"🔄 Attempting to cancel order {order.ticket} for {symbol if symbol else 'all symbols'}")
			
			result = mt5.order_send(request)
			if result.retcode != mt5.TRADE_RETCODE_DONE:
				Send_to_tele(f"❌ Failed to cancel order {order.ticket}: {result.comment}")
				return False
				
			Send_to_tele(f"✅ Order {order.ticket} cancelled successfully")
		return True
	except Exception as e:
		Send_to_tele(f"❌ Error cancelling orders: {e}")
		return False

def close_position(symbol):
	"""Close open position for symbol"""
	try:
		position = mt5.positions_get(symbol=symbol)
		if position is None or len(position) == 0:
			return True
			
		tick = mt5.symbol_info_tick(symbol)
		if tick is None:
			Send_to_tele(f"❌ Failed to get tick data for {symbol}")
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
		
		Send_to_tele(f"""
		🔄 Closing Position:
		Symbol: {symbol}
		Ticket: {position[0].ticket}
		Volume: {position[0].volume}
		Type: {'SELL' if position[0].type == 1 else 'BUY'}
		""")
		
		result = mt5.order_send(request)
		if result.retcode != mt5.TRADE_RETCODE_DONE:
			Send_to_tele(f"❌ Failed to close position: {result.comment}")
			return False
			
		Send_to_tele(f"✅ Position closed successfully")
		return True
	except Exception as e:
		Send_to_tele(f"❌ Error closing position: {e}")
		return False



def check_trading_hours():
	"""Check if current time is within trading hours (00:00-23:00) in New York timezone"""
	# Get NY timezone
	ny_tz = pytz.timezone('America/New_York')
	
	# Get current time in NY
	current_time = datetime.now(pytz.UTC).astimezone(ny_tz).time()
	
	# Define trading hours in NY time
	is_trading_time = current_time >= datetime.strptime("02:00", "%H:%M").time() and \
					 current_time <= datetime.strptime("15:00", "%H:%M").time()
	
	if not is_trading_time:
		Send_to_tele("⏰ Outside trading hours")
	return is_trading_time







def has_open_positions():
	"""Check if there are any open positions and close pending orders if found"""
	try:
		positions = mt5.positions_get()
		if positions is None:
			return False
			
		position_count = len(positions)
		
		if position_count > 0:
			positions_info = "\n".join([f"{p.symbol}: {p.volume} lots" for p in positions])
			Send_to_tele(f"""
			🔄 Open Positions Found:
			{positions_info}
			""")
		
			if position_count > 1:
				Send_to_tele(f"⚠️ Multiple positions detected ({position_count}). Closing one random position...")
				
				# Choose random position to close
				position_to_close = random.choice(positions)
				
				Send_to_tele(f"""
				🔄 Closing extra position:
				Symbol: {position_to_close.symbol}
				Ticket: {position_to_close.ticket}
				Type: {'Buy' if position_to_close.type == 0 else 'Sell'}
				Volume: {position_to_close.volume}
				""")
				close_position(position_to_close.symbol)

			# Get all active symbols
			active_symbols = [p.symbol for p in positions]
			Send_to_tele(f"Active symbols: {active_symbols}")
			
			# Cancel ALL pending orders when we have positions
			for symbol in SYMBOLS:
				orders = mt5.orders_get(symbol=symbol)
				if orders:
					Send_to_tele(f"🔄 Cancelling pending orders for {symbol}")
					cancel_all_orders(symbol)

		return position_count > 0
		
	except Exception as e:
		Send_to_tele(f"❌ Error checking positions: {e}")
		return True  # Return True on error to prevent new trades

	
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
