import os
import time
import uuid
import threading
import ccxt # For broker API
import asyncio # For async operations
import json
import pandas as pd
import discord
from alpaca.data.historical import StockHistoricalDataClient
import json
from alpaca.data.timeframe import TimeFrame # Import TimeFrame
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Importer les modules personnalisés
import data_handler as dh
import market_predictor as mp
import discord_reporter as dr # Import dr

# Charger les variables d'environnement
load_dotenv()

# --- Configuration ---
SYMBOL = os.getenv("TRADE_SYMBOL", "BTC/USDT")
TIMEFRAME_STR = os.getenv("TRADE_TIMEFRAME", "1Hour")
TIMEFRAME = getattr(TimeFrame, TIMEFRAME_STR.upper(), TimeFrame.Hour) # Map string to TimeFrame enum
TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", 100)) # Montant à trader en USD
STATE_FILE = "state.json"

# Paramètres de gestion des risques
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", 0.02))  # 2%
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.03))  # 3%
MAX_DAILY_DRAWDOWN_PCT = float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", 0.05)) # 5%

class TradingBot:
    def __init__(self):
        self.api_client = self._initialize_broker_api()
        self.state = self.load_state() # Charger l'état au démarrage
        self.state["is_running"] = True # S'assurer que le bot est toujours prêt à démarrer
        print("Bot de trading initialisé.")

    def _initialize_broker_api(self):
        """Initialise le client API Alpaca."""
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        # La valeur par défaut est True si la variable n'est pas définie ou n'est pas 'false'
        paper_trading = os.getenv("ALPACA_PAPER_TRADING", "true").lower() != 'false'
        
        if not api_key or not secret_key:
            print("ERREUR CRITIQUE: Les clés API Alpaca (ALPACA_API_KEY, ALPACA_SECRET_KEY) ne sont pas définies dans le fichier .env.")
            return None

        if paper_trading:
            print("Initialisation du client API Alpaca en mode PAPER TRADING...")
        else:
            print("Initialisation du client API Alpaca en mode LIVE TRADING...")

        return StockHistoricalDataClient(api_key, secret_key)

    def save_state(self):
        """Sauvegarde l'état actuel du bot dans un fichier JSON."""
        print("Sauvegarde de l'état du bot...")
        # La conversion en str pour datetime est nécessaire pour la sérialisation JSON
        state_to_save = self.state.copy()
        state_to_save["paused_until"] = self.state["paused_until"].isoformat() if self.state["paused_until"] else None
        state_to_save["last_daily_reset"] = self.state["last_daily_reset"].isoformat()
        # Ne pas sauvegarder les PNL non réalisés, ils sont calculés à la volée
        for pos in state_to_save.get("open_positions", []):
            pos.pop('unrealized_pnl', None)
            pos.pop('unrealized_pnl_pct', None)
            pos.pop('current_price', None)

        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=4)
        print("État sauvegardé.")

    def load_state(self):
        """Charge l'état du bot depuis un fichier JSON, sinon retourne un état par défaut."""
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                # Reconvertir les chaînes de date en objets datetime
                state["paused_until"] = datetime.fromisoformat(state["paused_until"]) if state["paused_until"] else None
                state["last_daily_reset"] = datetime.fromisoformat(state["last_daily_reset"]).date()
                print("État du bot chargé depuis le fichier.")
                return state
        except (FileNotFoundError, json.JSONDecodeError):
            print("Aucun état de sauvegarde valide trouvé. Initialisation avec un état par défaut.")
            return {
                "is_running": True,
                "is_paused": False,
                "paused_until": None,
                "daily_initial_balance": float(os.getenv("INITIAL_BALANCE", 10000)),
                "current_balance": float(os.getenv("INITIAL_BALANCE", 10000)),
                "open_positions": [],
                "last_daily_reset": datetime.now().date(),
                "current_trading_symbol": os.getenv("TRADE_SYMBOL", "SPY"),
                "monitored_stocks": [s.strip() for s in os.getenv("MONITORED_STOCKS", "").split(',') if s.strip()],
                "news_sentiment_threshold": float(os.getenv("NEWS_SENTIMENT_THRESHOLD", 0.8)),
                "send_trade_alerts": True,
                "trade_amount_usd": TRADE_AMOUNT_USD
            }

    def get_state(self):
        """Retourne l'état actuel du bot, y compris le PNL non réalisé."""
        open_positions_with_pnl = []
        total_unrealized_pnl = 0.0

        # It's better to fetch prices for all symbols at once if possible, but for now, we do it one by one.
        for position in self.state["open_positions"]:
            try:
                market_data = dh.get_market_data(self.api_client, position["symbol"], TIMEFRAME, limit=1)
                current_price = market_data['Close'].iloc[-1] if not market_data.empty else position['price']

                # Calculate unrealized PNL
                if position["side"] == "buy":
                    unrealized_pnl = (current_price - position["price"]) * position["amount"]
                else:  # sell
                    unrealized_pnl = (position["price"] - current_price) * position["amount"]
                
                unrealized_pnl_pct = (unrealized_pnl / position["cost"]) * 100 if position["cost"] > 0 else 0
                total_unrealized_pnl += unrealized_pnl

                position_copy = position.copy()
                position_copy["unrealized_pnl"] = unrealized_pnl
                position_copy["unrealized_pnl_pct"] = unrealized_pnl_pct
                position_copy["current_price"] = current_price
                open_positions_with_pnl.append(position_copy)
            except Exception as e:
                print(f"Impossible de calculer le PNL pour {position['symbol']}: {e}")
                position_copy = position.copy()
                position_copy["unrealized_pnl"] = 0
                position_copy["unrealized_pnl_pct"] = 0
                position_copy["current_price"] = position['price']
                open_positions_with_pnl.append(position_copy)

        effective_balance = self.state["current_balance"] + total_unrealized_pnl

        return {
            "is_running": self.state["is_running"],
            "is_paused": self.state["is_paused"],
            "paused_until": self.state["paused_until"],
            "daily_initial_balance": self.state["daily_initial_balance"],
            "current_balance": self.state["current_balance"],
            "effective_balance": effective_balance,
            "open_positions": open_positions_with_pnl,
            "current_trading_symbol": self.state["current_trading_symbol"],
            "send_trade_alerts": self.state["send_trade_alerts"],
            "trade_amount_usd": self.state["trade_amount_usd"]
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
        if self.state["send_trade_alerts"]:
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


    async def _execute_trade(self, side, price, market_data_with_indicators, is_manual=False):
        """Simule l'exécution d'un ordre de trading et gère les positions."""
        trade_id = f"TRADE-{uuid.uuid4()}"
        print(f"EXECUTION D'ORDRE ({side.upper()}) -> ID: {trade_id}, Prix: {price}, Montant: {self.state['trade_amount_usd']}$ ")
        
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
            'symbol': self.state['current_trading_symbol'],
            'type': 'market', # Assuming market orders for simplicity
            'side': side,
            'price': price,
            'amount': self.state['trade_amount_usd'] / price, # Amount in base currency
            'cost': self.state['trade_amount_usd'], # Cost in quote currency
            'status': 'open',
            'profit': 0, # Initial profit is 0
            'stop_loss': stop_loss_price,
            'take_profit': take_profit_price,
            'is_manual': is_manual
        }
        
        dh.log_trade(trade_log)
        self.state["open_positions"].append(trade_log)
        
        if self.state["send_trade_alerts"]:
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

    def set_trade_alerts(self, enable: bool):
        """Active ou désactive l'envoi d'alertes de trade sur Discord."""
        self.state["send_trade_alerts"] = enable
        print(f"Alertes de trade Discord: {'Activées' if enable else 'Désactivées'}")

    async def close_trade_by_id(self, trade_id: str):
        """Clôture manuellement une position ouverte par son ID."""
        position_to_close = next((p for p in self.state["open_positions"] if p["trade_id"] == trade_id), None)

        if not position_to_close:
            msg = f"Aucune position ouverte trouvée avec l'ID: {trade_id}"
            print(msg)
            return False, msg

        try:
            symbol = position_to_close["symbol"]
            market_data = dh.get_market_data(self.api_client, symbol, TIMEFRAME, limit=1)
            if market_data.empty:
                msg = f"Impossible de récupérer le prix actuel pour {symbol}."
                return False, msg
            
            current_price = market_data['Close'].iloc[-1]
            
            profit_loss_pct = (current_price - position_to_close["price"]) / position_to_close["price"] if position_to_close["side"] == "buy" else (position_to_close["price"] - current_price) / position_to_close["price"]

            await self._close_position(position_to_close, current_price, "manual_close", profit_loss_pct)
            msg = f"Position {trade_id} fermée manuellement au prix de ${current_price:.2f}."
            return True, msg
        except Exception as e:
            msg = f"Erreur lors de la clôture de la position: {e}"
            print(f"Erreur lors de la clôture manuelle de la position {trade_id}: {e}")
            return False, msg

    async def manual_execute_trade(self, symbol: str, side: str, amount_usd: float):
        """Exécute un ordre de trading manuellement."""
        print(f"Tentative d'exécution manuelle: {side} {amount_usd}$ sur {symbol}")
        # 1. Valider le symbole
        market_data = dh.get_market_data(self.api_client, symbol, TIMEFRAME, limit=1)
        if market_data is None or market_data.empty:
            msg = f"Le symbole '{symbol}' est invalide ou aucune donnée de marché n'a pu être récupérée."
            await dr.send_report({"title": "Erreur Ordre Manuel", "message": msg, "color": discord.Color.red()})
            return False

        try:
            current_price = market_data['Close'].iloc[-1]
            market_data_with_indicators = dh.calculate_indicators(market_data) # Needed for ATR

            await self._execute_trade(side, current_price, market_data_with_indicators, is_manual=True)
            await dr.send_report({"title": "Ordre Manuel Exécuté", "message": f"Ordre manuel **{side.upper()} {amount_usd}$** sur **{symbol}** exécuté au prix de **${current_price:.2f}**.", "color": discord.Color.green()})
            return True
        except Exception as e:
            print(f"Erreur lors de l'exécution manuelle de l'ordre: {e}")
            await dr.send_report({"title": "Erreur Ordre Manuel", "message": f"Une erreur est survenue lors de l'exécution de l'ordre manuel: {e}", "color": discord.Color.red()})
            return False

    def set_trade_amount(self, amount_usd: float):
        """Définit le montant de trade en USD."""
        self.state["trade_amount_usd"] = amount_usd
        print(f"Montant de trade défini à {amount_usd}$.")

    def set_trading_symbol(self, symbol: str):
        """Définit le symbole de trading principal."""
        self.state["current_trading_symbol"] = symbol
        print(f"Symbole de trading principal défini à {symbol}.")

    def get_recent_trades(self, hours: int = 24):
        """Récupère les trades journalisés des dernières X heures."""
        try:
            if not os.path.exists(dh.TRADES_FILE):
                return []
            
            df = pd.read_parquet(dh.TRADES_FILE)
            # Ensure timestamp is datetime and filter
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            time_threshold = datetime.now() - timedelta(hours=hours)
            recent_trades = df[df['timestamp'] >= time_threshold].to_dict(orient='records')
            return recent_trades
        except Exception as e:
            print(f"Erreur lors de la récupération des trades récents: {e}")
            return []

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
            if self.state["send_trade_alerts"]:
                await dr.send_report({
                    "title": "Opportunité d'Actualité Détectée",
                    "message": f"Le bot va temporairement trader **{best_opportunity_symbol}** en raison d'un sentiment d'actualité fort ({highest_sentiment_score:.2f}).",
                    "color": discord.Color.purple()
                })
        elif not best_opportunity_symbol and self.state["current_trading_symbol"] != SYMBOL: # Revert to default if no strong news
            self.state["current_trading_symbol"] = SYMBOL
            print(f"Revenant au symbole de trading par défaut : {SYMBOL}.")
            if self.state["send_trade_alerts"]:
                await dr.send_report({
                    "title": "Retour au Trading d'Indice",
                    "message": f"Aucune nouvelle opportunité détectée. Retour au trading de **{SYMBOL}**.",
                    "color": discord.Color.light_gray()
                })

    async def main_loop(self):
        """La boucle de trading principale."""
        print("Lancement de la boucle de trading principale...")
        loop = asyncio.get_running_loop()
        
        while self.state["is_running"]:
            await self._reset_daily_balance() # Check and reset daily balance if needed

            if self.state["is_paused"]:
                if self.state["paused_until"] and datetime.now() >= self.state["paused_until"]:
                    self.resume() # Auto-resume if pause time is over
                else:
                    print("Bot en pause. Attente...")
                    await asyncio.sleep(60) # Wait 1 minute before re-checking
                    continue

            # Check for news opportunities every hour (or adjust frequency)
            if datetime.now().minute == 0: # Check at the top of the hour
                await self._check_for_news_opportunities()

            # 1. Récupérer et analyser les données de marché pour le symbole actuel (non-blocking)
            market_data = await loop.run_in_executor(
                None, dh.get_market_data, self.api_client, self.state["current_trading_symbol"], TIMEFRAME, 100
            )
            
            if market_data is None or market_data.empty:
                print("Aucune donnée de marché reçue, cycle suivant.")
                await asyncio.sleep(300) # Attendre 5 minutes avant de réessayer
                continue

            # 2. Calculer les indicateurs (non-blocking)
            market_data_with_indicators = await loop.run_in_executor(
                None, dh.calculate_indicators, market_data
            )

            # 3. Obtenir le signal de trading (non-blocking)
            signal = await loop.run_in_executor(
                None, mp.get_trading_signal, market_data_with_indicators
            )
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
            await asyncio.sleep(3600) # Wait for 1 hour (adjust as needed for timeframe)

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
        except Exception as e:
            print(f"Une erreur critique est survenue: {e}")
        finally:
            self.state["is_running"] = False
            self.save_state() # Sauvegarder l'état à l'arrêt
            # Optionally send a critical error report to Discord
            # asyncio.run(dr.send_report({"title": "ERREUR CRITIQUE", "message": f"Le bot a rencontré une erreur: {e}", "color": discord.Color.red()}))

if __name__ == "__main__":
    bot = TradingBot()
    if bot.api_client is None:
        print("Arrêt du bot car le client API n'a pas pu être initialisé.")
    else:
        bot.run()