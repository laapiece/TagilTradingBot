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

DATA_DIR = "data"
TRADES_FILE = os.path.join(DATA_DIR, "trades.parquet")

def get_market_data(api_client: StockHistoricalDataClient, symbol="AAPL", timeframe=TimeFrame.Hour, limit=100):
    """Récupère les données de marché OHLCV via l'API Alpaca."""
    print(f"Récupération des {limit} dernières bougies pour {symbol} en {timeframe}...")
    try:
        if not api_client:
            raise ValueError("Client API Alpaca non initialisé.")
        
        # Définir la période de temps pour la requête
        end_date = datetime.now()
        start_date = end_date - timedelta(days=limit * timeframe.value) # Approximation

        request_params = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=timeframe,
            start=start_date,
            end=end_date
        )
        
        bars = api_client.get_stock_bars(request_params).df
        
        if bars.empty:
            raise ValueError("Aucune donnée Alpaca reçue.")

        # Alpaca retourne un DataFrame multi-indexé, on le simplifie
        df = bars.loc[symbol].reset_index()
        df = df.rename(columns={'timestamp': 'timestamp', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(by='timestamp').tail(limit) # S'assurer de l'ordre et de la limite

        print("Données de marché Alpaca récupérées.")
        return df
    except Exception as e:
        print(f"Erreur lors de la récupération des données de marché Alpaca : {e}. Utilisation des données de test.")
        # Fallback sur des données de test si l'API échoue
        data = {
            'Open': [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113],
            'High': [103, 104, 103, 105, 106, 106, 108, 110, 109, 111, 112, 114, 113, 115],
            'Low': [99, 101, 100, 102, 104, 103, 105, 107, 106, 108, 109, 110, 110, 112],
            'Close': [102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 114],
            'Volume': [10000, 11000, 10500, 12000, 11500, 12500, 13000, 12800, 13500, 14000, 14500, 14200, 14800, 15000]
        }
        df = pd.DataFrame(data)
        return df

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
