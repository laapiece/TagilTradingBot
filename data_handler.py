# data_handler.py
"""
Centralise l'acquisition et le prétraitement des données.
- Récupère les données de marché (OHLCV) via API.
- Calcule les indicateurs techniques (RSI, MACD, Bollinger, ATR).
- Récupère les actualités via NewsAPI.
- Journalise les trades au format Parquet.
"""
import os
import pandas as pd
import pandas_ta as ta
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.historical import StockHistoricalDataClient
from datetime import datetime, timedelta
from requests.exceptions import HTTPError

DATA_DIR = "data"
TRADES_FILE = os.path.join(DATA_DIR, "trades.parquet")

def get_market_data(api_client: StockHistoricalDataClient, symbol="AAPL", timeframe=TimeFrame.Hour, limit=100):
    """Récupère les données de marché OHLCV via l'API Alpaca."""
    if not isinstance(limit, int) or limit <= 0:
        print("Erreur: La limite doit être un entier positif.")
        return None

    print(f"Récupération des {limit} dernières bougies pour {symbol} en {timeframe}...")
    try:
        if not api_client:
            raise ValueError("Client API Alpaca non initialisé.")
        
        # Définir la période de temps pour la requête
        end_date = pd.Timestamp.now(tz='America/New_York').floor('1min') # Use pandas for timezone-aware timestamp
        # Calculate start_date based on timeframe and limit to ensure enough data is fetched
        if timeframe.unit == 'Min':
            delta = timedelta(minutes=timeframe.amount * limit)
        elif timeframe.unit == 'Hour':
            delta = timedelta(hours=timeframe.amount * limit)
        elif timeframe.unit == 'Day':
            delta = timedelta(days=timeframe.amount * limit)
        else:
            delta = timedelta(days=30) # Default for other timeframes
        start_date = end_date - delta

        request_params = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=timeframe,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            adjustment='raw' # Use raw data
        )
        
        bars = api_client.get_stock_bars(request_params).df
        
        if bars.empty:
            print(f"Avertissement : Aucune donnée de marché reçue d'Alpaca pour {symbol}.")
            return None

        # Alpaca retourne un DataFrame multi-indexé, on le simplifie
        df = bars.loc[symbol].reset_index()
        df = df.rename(columns={'timestamp': 'timestamp', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(by='timestamp').tail(limit) # S'assurer de l'ordre et de la limite

        print("Données de marché Alpaca récupérées.")
        return df
    except HTTPError as e:
        if e.response.status_code == 403:
            print(f"ERREUR: Accès refusé (403 Forbidden) pour {symbol}. Veuillez vérifier vos clés API Alpaca et votre abonnement aux données. Détails: {e}")
        else:
            print(f"Erreur HTTP lors de la récupération des données de marché Alpaca pour {symbol} : {e}")
        return None
    except Exception as e:
        print(f"Erreur critique lors de la récupération des données de marché Alpaca pour {symbol} : {e}")
        return None

def calculate_indicators(df: pd.DataFrame):
    """Calcule tous les indicateurs techniques nécessaires."""
    if df.empty:
        return df
    print("Calcul des indicateurs techniques (RSI, MACD, BBands, ATR)...")
    df.ta.rsi(append=True)
    df.ta.macd(append=True)
    df.ta.bbands(append=True)
    df.ta.atr(append=True)
    return df

def log_trade(trade_data: dict):
    """Journalise un trade individuel dans un fichier Parquet."""
    print(f"Journalisation du trade : {trade_data['trade_id']}")
    df = pd.DataFrame([trade_data])
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(TRADES_FILE):
            existing_df = pd.read_parquet(TRADES_FILE)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
        else:
            combined_df = df
        
        combined_df.to_parquet(TRADES_FILE, engine='pyarrow', index=False)
        print(f"Trade {trade_data['trade_id']} journalisé dans {TRADES_FILE}")

    except Exception as e:
        print(f"Erreur lors de la journalisation du trade : {e}")

if __name__ == '__main__':
    # Exemple d'utilisation avec Alpaca
    from dotenv import load_dotenv
    load_dotenv()
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

    if ALPACA_API_KEY and ALPACA_SECRET_KEY:
        alpaca_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        market_data = get_market_data(alpaca_client, symbol="AAPL", timeframe=TimeFrame.Day, limit=20)
        if not market_data.empty:
            market_data_with_indicators = calculate_indicators(market_data)
            print("\nDataFrame avec indicateurs:")
            print(market_data_with_indicators.tail())
    else:
        print("Clés API Alpaca non configurées. Utilisation des données de test.")
        market_data = get_market_data(None) # Utilise les données de test
        if not market_data.empty:
            market_data_with_indicators = calculate_indicators(market_data)
            print("\nDataFrame avec indicateurs:")
            print(market_data_with_indicators.tail())

    from datetime import datetime
    example_trade = {
        'trade_id': 'T12345',
        'timestamp': datetime.now(),
        'symbol': 'AAPL',
        'type': 'limit',
        'side': 'buy',
        'price': 114.5,
        'amount': 1.0,
        'cost': 114.5,
        'status': 'closed',
        'profit': 2.0,
        'stop_loss': 112.21,
        'take_profit': 117.93
    }
    log_trade(example_trade)
