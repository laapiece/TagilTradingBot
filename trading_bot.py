# trading_bot.py
"""
Cœur logique du bot de trading.
Orchestre les modules, gère l'état, exécute les trades
et applique la gestion des risques.
"""

import os
import time
import uuid
import threading
import ccxt # For broker API
import asyncio # For async operations
from alpaca.data.timeframe import TimeFrame # Import TimeFrame
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Importer les modules personnalisés
import data_handler as dh
import market_predictor as mp
import discord_reporter as dr

# Charger les variables d'environnement
load_dotenv()

# --- Configuration ---
SYMBOL = os.getenv("TRADE_SYMBOL", "BTC/USDT")
TIMEFRAME_STR = os.getenv("TRADE_TIMEFRAME", "1Hour")
TIMEFRAME = getattr(TimeFrame, TIMEFRAME_STR.upper(), TimeFrame.Hour) # Map string to TimeFrame enum
TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", 100)) # Montant à trader en USD

# Paramètres de gestion des risques
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 0.02))  # 2%
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.03))  # 3%
MAX_DAILY_DRAWDOWN_PCT = float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", 0.05)) # 5%

class TradingBot:
    def __init__(self):
        self.api_client = self._initialize_broker_api()
        self.state = {
            "is_running": True,
            "is_paused": False,
            "paused_until": None,
            "daily_initial_balance": float(os.getenv("INITIAL_BALANCE", 10000)),
            "current_balance": float(os.getenv("INITIAL_BALANCE", 10000)),
            "open_positions": [], # List of dicts, each representing an open trade
            "last_daily_reset": datetime.now().date(),
            "current_trading_symbol": os.getenv("TRADE_SYMBOL", "SPY"), # Default to index ETF
            "monitored_stocks": [s.strip() for s in os.getenv("MONITORED_STOCKS", "").split(',') if s.strip()],
            "news_sentiment_threshold": float(os.getenv("NEWS_SENTIMENT_THRESHOLD", 0.8))
        }
        print("Bot de trading initialisé.")

    def _initialize_broker_api(self):
        # Placeholder for actual CCXT initialization
        # You would typically get API keys from .env
        # exchange_id = os.getenv("EXCHANGE_ID", "binance")
        # api_key = os.getenv("API_KEY")
        # secret = os.getenv("SECRET")
        # exchange_class = getattr(ccxt, exchange_id)
        # return exchange_class({
        #     'apiKey': api_key,
        #     'secret': secret,
        #     'enableRateLimit': True,
        # })
        print("Initialisation de l'API du broker (placeholder)...")
        return None # Return None for now, using test data

    def get_state(self):
        """Retourne l'état actuel du bot pour le reporter Discord."""
        return {
            "is_running": self.state["is_running"],
            "is_paused": self.state["is_paused"],
            "paused_until": self.state["paused_until"],
            "daily_initial_balance": self.state["daily_initial_balance"],
            "current_balance": self.state["current_balance"],
            "open_positions": self.state["open_positions"] # Consider returning a copy or simplified version
        }

    def pause(self, minutes: int):
        """Met le bot en pause pour une durée spécifiée."""
        self.state["is_paused"] = True
        self.state["paused_until"] = datetime.now() + timedelta(minutes=minutes)
        print(f"Bot mis en pause jusqu'à {self.state['paused_until']}")

    def resume(self):
        """Reprend les opérations du bot."""
        self.state["is_paused"] = False
        self.state["paused_until"] = None
        print("Bot a repris ses opérations.")

    async def _reset_daily_balance(self):
        """Réinitialise le solde initial journalier si un nouveau jour commence."""
        today = datetime.now().date()
        if today > self.state["last_daily_reset"]:
            self.state["daily_initial_balance"] = self.state["current_balance"]
            self.state["last_daily_reset"] = today
            print(f"Solde initial journalier réinitialisé à {self.state['daily_initial_balance']:.2f}")
            await dr.send_report({
                "title": "Réinitialisation Quotidienne",
                "message": f"Le solde initial journalier a été réinitialisé à **${self.state['daily_initial_balance']:.2f}**.",
                "color": discord.Color.light_gray()
            })

    async def _check_risk_management(self, current_price, market_data_with_indicators):
        """Vérifie si un stop-loss ou take-profit a été touché pour les positions ouvertes."""
        positions_to_close = []
        for position in self.state["open_positions"]:
            if position["status"] == "open":
                profit_loss_pct = (current_price - position["price"]) / position["price"] if position["side"] == "buy" else (position["price"] - current_price) / position["price"]

                # Check Stop-Loss
                if position["side"] == "buy" and current_price <= position["stop_loss"]:
                    print(f"SL BUY hit for {position['trade_id']}. Current: {current_price}, SL: {position['stop_loss']}")
                    positions_to_close.append((position, "stop_loss", profit_loss_pct))
                elif position["side"] == "sell" and current_price >= position["stop_loss"]:
                    print(f"SL SELL hit for {position['trade_id']}. Current: {current_price}, SL: {position['stop_loss']}")
                    positions_to_close.append((position, "stop_loss", profit_loss_pct))
                
                # Check Take-Profit
                elif position["side"] == "buy" and current_price >= position["take_profit"]:
                    print(f"TP BUY hit for {position['trade_id']}. Current: {current_price}, TP: {position['take_profit']}")
                    positions_to_close.append((position, "take_profit", profit_loss_pct))
                elif position["side"] == "sell" and current_price <= position["take_profit"]:
                    print(f"TP SELL hit for {position['trade_id']}. Current: {current_price}, TP: {position['take_profit']}")
                    positions_to_close.append((position, "take_profit", profit_loss_pct))

        for position, reason, profit_loss_pct in positions_to_close:
            await self._close_position(position, current_price, reason, profit_loss_pct)

        # Check Daily Drawdown
        drawdown = (self.state['daily_initial_balance'] - self.state['current_balance']) / self.state['daily_initial_balance']
        if drawdown > MAX_DAILY_DRAWDOWN_PCT:
            print(f"ARRÊT D'URGENCE : Drawdown journalier de {drawdown:.2%} dépassé!")
            self.state["is_running"] = False
            await dr.send_report({
                "title": "ALERTE : ARRÊT D'URGENCE",
                "message": f"Le drawdown journalier de **{drawdown:.2%}** a dépassé le seuil de **{MAX_DAILY_DRAWDOWN_PCT:.2%}**. Le bot est arrêté.",
                "color": discord.Color.red(),
                "fields": [
                    {"name": "Solde Initial Journalier", "value": f"${self.state['daily_initial_balance']:.2f}", "inline": True},
                    {"name": "Solde Actuel", "value": f"${self.state['current_balance']:.2f}", "inline": True}
                ]
            })

    async def _close_position(self, position, close_price, reason, profit_loss_pct):
        """Clôture une position et met à jour le solde."""
        position["status"] = "closed"
        position["close_price"] = close_price
        position["close_timestamp"] = datetime.now()
        
        # Calculate actual profit/loss in USD
        if position["side"] == "buy":
            profit_usd = (close_price - position["price"]) * position["amount"]
        else: # sell
            profit_usd = (position["price"] - close_price) * position["amount"]
        
        position["profit"] = profit_usd
        self.state["current_balance"] += profit_usd # Update balance

        dh.log_trade(position) # Log the closed trade

        print(f"Position {position['trade_id']} fermée ({reason}). P&L: ${profit_usd:.2f} ({profit_loss_pct:.2%})")
        await dr.send_report({
            "title": f"Position Fermée ({reason.replace('_', ' ').title()})",
            "message": f"La position **{position['trade_id']}** sur **{position['symbol']}** a été fermée.",
            "color": discord.Color.green() if profit_usd >= 0 else discord.Color.red(),
            "fields": [
                {"name": "Type", "value": position["side"].upper(), "inline": True},
                {"name": "Prix d'Ouverture", "value": f"${position['price']:.2f}", "inline": True},
                {"name": "Prix de Clôture", "value": f"${close_price:.2f}", "inline": True},
                {"name": "P&L", "value": f"${profit_usd:.2f} ({profit_loss_pct:.2%})", "inline": True},
                {"name": "Solde Actuel", "value": f"${self.state['current_balance']:.2f}", "inline": True}
            ]
        })
        # Remove from open positions
        self.state["open_positions"] = [p for p in self.state["open_positions"] if p["trade_id"] != position["trade_id"]]


    async def _execute_trade(self, side, price, market_data_with_indicators):
        """Simule l'exécution d'un ordre de trading et gère les positions."""
        trade_id = f"TRADE-{uuid.uuid4()}"
        print(f"EXECUTION D'ORDRE ({side.upper()}) -> ID: {trade_id}, Prix: {price}, Montant: {TRADE_AMOUNT_USD}$ ")
        
        # Get latest ATR for Take-Profit adjustment
        atr_value = market_data_with_indicators['ATR_14'].iloc[-1] if 'ATR_14' in market_data_with_indicators.columns else 0.0

        if side == 'buy':
            stop_loss_price = price * (1 - STOP_LOSS_PCT)
            take_profit_price = price + (TAKE_PROFIT_PCT * price) + (atr_value * 0.5) # Example ATR adjustment
        else: # sell
            stop_loss_price = price * (1 + STOP_LOSS_PCT)
            take_profit_price = price - (TAKE_PROFIT_PCT * price) - (atr_value * 0.5) # Example ATR adjustment

        trade_log = {
            'trade_id': trade_id,
            'timestamp': datetime.now(),
            'symbol': SYMBOL,
            'type': 'market', # Assuming market orders for simplicity
            'side': side,
            'price': price,
            'amount': TRADE_AMOUNT_USD / price, # Amount in base currency
            'cost': TRADE_AMOUNT_USD, # Cost in quote currency
            'status': 'open',
            'profit': 0, # Initial profit is 0
            'stop_loss': stop_loss_price,
            'take_profit': take_profit_price
        }
        
        dh.log_trade(trade_log)
        self.state["open_positions"].append(trade_log)
        
        await dr.send_report({
            "title": "Nouvelle Position Ouverte",
            "message": f"Une nouvelle position **{side.upper()}** a été ouverte sur **{self.state['current_trading_symbol']}**.",
            "color": discord.Color.blue(),
            "fields": [
                {"name": "ID du Trade", "value": trade_id, "inline": True},
                {"name": "Prix d'Ouverture", "value": f"${price:.2f}", "inline": True},
                {"name": "Montant", "value": f"{trade_log['amount']:.4f} {self.state['current_trading_symbol'].split('/')[0]}", "inline": True},
                {"name": "Stop-Loss", "value": f"${stop_loss_price:.2f}", "inline": True},
                {"name": "Take-Profit", "value": f"${take_profit_price:.2f}", "inline": True}
            ]
        })

    async def _check_for_news_opportunities(self):
        """Vérifie les actualités pour les actions surveillées et ajuste le symbole de trading."""
        if not self.state["monitored_stocks"]:
            return

        print("Vérification des opportunités d'actualités...")
        best_opportunity_symbol = None
        highest_sentiment_score = 0.0

        for stock_symbol in self.state["monitored_stocks"]:
            sentiment = mp.get_news_sentiment(query=stock_symbol)
            print(f"Sentiment pour {stock_symbol}: {sentiment:.2f}")
            
            # Check for strong positive or negative sentiment
            if sentiment >= self.state["news_sentiment_threshold"] or sentiment <= (1 - self.state["news_sentiment_threshold"]):
                # Prioritize stronger sentiment
                if abs(sentiment - 0.5) > abs(highest_sentiment_score - 0.5):
                    highest_sentiment_score = sentiment
                    best_opportunity_symbol = stock_symbol
        
        if best_opportunity_symbol and self.state["current_trading_symbol"] != best_opportunity_symbol:
            self.state["current_trading_symbol"] = best_opportunity_symbol
            print(f"Symbole de trading ajusté à {best_opportunity_symbol} en raison d'actualités intéressantes (Sentiment: {highest_sentiment_score:.2f}).")
            await dr.send_report({
                "title": "Opportunité d'Actualité Détectée",
                "message": f"Le bot va temporairement trader **{best_opportunity_symbol}** en raison d'un sentiment d'actualité fort ({highest_sentiment_score:.2f}).",
                "color": discord.Color.purple()
            })
        elif not best_opportunity_symbol and self.state["current_trading_symbol"] != SYMBOL: # Revert to default if no strong news
            self.state["current_trading_symbol"] = SYMBOL
            print(f"Revenant au symbole de trading par défaut : {SYMBOL}.")
            await dr.send_report({
                "title": "Retour au Trading d'Indice",
                "message": f"Aucune nouvelle opportunité détectée. Retour au trading de **{SYMBOL}**.",
                "color": discord.Color.light_gray()
            })

    async def main_loop(self):
        """La boucle de trading principale."""
        print("Lancement de la boucle de trading principale...")
        
        while self.state["is_running"]:
            await self._reset_daily_balance() # Check and reset daily balance if needed

            if self.state["is_paused"]:
                if self.state["paused_until"] and datetime.now() >= self.state["paused_until"]:
                    self.resume() # Auto-resume if pause time is over
                else:
                    print("Bot en pause. Attente...")
                    time.sleep(60) # Wait 1 minute before re-checking
                    continue

            # Check for news opportunities every hour (or adjust frequency)
            if datetime.now().minute == 0: # Check at the top of the hour
                await self._check_for_news_opportunities()

            # 1. Récupérer et analyser les données de marché pour le symbole actuel
            market_data = dh.get_market_data(self.api_client, self.state["current_trading_symbol"], TIMEFRAME)
            
            if market_data.empty:
                print("Aucune donnée de marché reçue, cycle suivant.")
                time.sleep(300) # Attendre 5 minutes avant de réessayer
                continue

            # 2. Calculer les indicateurs
            market_data_with_indicators = dh.calculate_indicators(market_data)

            # 3. Obtenir le signal de trading
            signal = mp.get_trading_signal(market_data_with_indicators)
            current_price = market_data['Close'].iloc[-1]

            print(f"Signal actuel pour {self.state['current_trading_symbol']}: {signal:.4f} | Prix actuel: {current_price}")

            # 4. Gérer les positions ouvertes (vérifier SL/TP)
            await self._check_risk_management(current_price, market_data_with_indicators)

            # 5. Logique de décision pour ouvrir de nouvelles positions
            if not self.state["open_positions"]: # Only open new position if no open positions
                if signal > 0.75: # Seuil d'achat fort
                    await self._execute_trade('buy', current_price, market_data_with_indicators)
                elif signal < 0.25: # Seuil de vente fort
                    await self._execute_trade('sell', current_price, market_data_with_indicators)
            else:
                print("Position(s) ouverte(s), pas de nouvelle décision d'ouverture.")

            # Attendre avant le prochain cycle (ex: 1 heure)
            print("Cycle terminé. En attente du prochain...")
            time.sleep(3600) # Wait for 1 hour (adjust as needed for timeframe)

    def run(self):
        """Point d'entrée principal pour démarrer le bot."""
        # Démarrer le bot Discord dans un thread séparé
        discord_thread = threading.Thread(target=dr.start_discord_bot, args=(self,), daemon=True)
        discord_thread.start()
        
        try:
            # Run the main trading loop (which is now async, so needs an event loop)
            asyncio.run(self.main_loop())
        except KeyboardInterrupt:
            print("Arrêt manuel du bot.")
            self.state["is_running"] = False
        except Exception as e:
            print(f"Une erreur critique est survenue: {e}")
            self.state["is_running"] = False
            # Optionally send a critical error report to Discord
            # asyncio.run(dr.send_report({"title": "ERREUR CRITIQUE", "message": f"Le bot a rencontré une erreur: {e}", "color": discord.Color.red()}))

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()