# market_predictor.py
"""
Moteur de prédiction.
Intègre le modèle IA local, l'analyse de sentiment
et les indicateurs techniques pour générer le signal de trading.
"""
import os
import torch
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from newsapi import NewsApiClient

# Charger les variables d'environnement
load_dotenv()

# --- Configuration ---
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
MODEL_ID = "stabilityai/stablelm-3b-4e1t"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# --- Initialisation des clients et du modèle ---

# Configuration de la quantification 4-bit
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16
)

# Charger le modèle et le tokenizer
# Note : Le téléchargement du modèle se produira lors de la première exécution
try:
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=quantization_config if DEVICE == "cuda" else None, # Only apply quantization if CUDA is available
        device_map="auto" if DEVICE == "cuda" else None, # Auto device mapping for CUDA
        trust_remote_code=True
    ).to(DEVICE) # Move model to appropriate device
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    print(f"Modèle IA chargé avec succès sur {DEVICE}.")
except Exception as e:
    print(f"Erreur lors du chargement du modèle IA : {e}")
    model = None
    tokenizer = None

# Client NewsAPI
newsapi = NewsApiClient(api_key=NEWS_API_KEY)

def get_news_sentiment(query="finance OR stock OR market"):
    """Récupère les actualités et retourne un score de sentiment simple."""
    if not NEWS_API_KEY:
        print("Avertissement : Clé API NewsAPI non configurée. Retour d'une valeur neutre.")
        return 0.5 

    try:
        all_articles = newsapi.get_everything(q=query, language='en', sort_by='relevancy', page_size=20)
        
        sentiment_score = 0.5
        positive_words = ['gain', 'bullish', 'up', 'high', 'profit', 'good', 'strong', 'growth', 'rise', 'positive', 'success']
        negative_words = ['loss', 'bearish', 'down', 'low', 'bad', 'risk', 'weak', 'decline', 'fall', 'negative', 'failure']
        
        for article in all_articles['articles']:
            content = (article['title'] + " " + str(article['description'])).lower() # Ensure description is string
            sentiment_score += sum(1 for word in positive_words if word in content) * 0.03
            sentiment_score -= sum(1 for word in negative_words if word in content) * 0.03
            
        return max(0, min(1, sentiment_score)) # Clamp score between 0 and 1
    except Exception as e:
        print(f"Erreur lors de la récupération des actualités : {e}")
        return 0.5 # Return neutral on error

def get_ia_score(market_data: pd.DataFrame):
    """Génère un score prédictif à partir des données de marché avec le modèle IA."""
    if model is None or tokenizer is None:
        print("Avertissement : Modèle IA non disponible. Retour d'un score neutre.")
        return 0.5

    # Prepare the prompt for the model
    prompt_data = market_data.to_string(index=False)
    prompt = f"""Given the following market data, predict the market direction.
Data:
{prompt_data}

Based on this data, is the short-term outlook bullish or bearish?
Answer (bullish/bearish):"""

    inputs = tokenizer(prompt, return_tensors="pt").to(DEVICE)
    outputs = model.generate(**inputs, max_new_tokens=5, temperature=0.1)
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # Interpret the response
    if "bullish" in response.lower():
        return 0.8
    elif "bearish" in response.lower():
        return 0.2
    return 0.5 # Neutral if response is uncertain

def get_trading_signal(market_data: pd.DataFrame):
    """Calcule le signal de trading final en combinant les différentes sources."""
    print("Génération du signal de trading...")

    # 1. Calcul des indicateurs techniques
    # Ensure the DataFrame has enough data for indicators
    if len(market_data) < 14: # RSI_14 needs at least 14 periods
        print("Données insuffisantes pour calculer les indicateurs. Retour d'un signal neutre.")
        return 0.5

    market_data.ta.rsi(append=True)
    market_data.ta.macd(append=True)
    market_data.ta.bbands(append=True)
    
    # Normaliser le RSI entre 0 et 1
    rsi_normalized = market_data['RSI_14'].iloc[-1] / 100.0 if 'RSI_14' in market_data.columns else 0.5

    # 2. Obtenir le score du sentiment des actualités
    news_sentiment = get_news_sentiment()

    # 3. Obtenir le score de l'IA
    ia_score = get_ia_score(market_data)
    
    print(f"Scores -> IA: {ia_score:.2f}, News: {news_sentiment:.2f}, RSI: {rsi_normalized:.2f}")

    # 4. Calculer le signal final pondéré
    signal = (ia_score * 0.7) + (news_sentiment * 0.2) + (rsi_normalized * 0.1)
    
    return signal

if __name__ == '__main__':
    # Exemple d'utilisation avec des données de placeholder
    from data_handler import get_market_data
    
    # Simuler des données sur une plus longue période pour les indicateurs
    data = {
        'Open': [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 114, 115, 116, 117, 118, 119],
        'High': [103, 104, 103, 105, 106, 106, 108, 110, 109, 111, 112, 114, 113, 115, 116, 117, 118, 119, 120, 121],
        'Low': [99, 101, 100, 102, 104, 103, 105, 107, 106, 108, 109, 110, 110, 112, 113, 114, 115, 116, 117, 118],
        'Close': [102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 114, 115, 116, 117, 118, 119, 120],
        'Volume': [10000, 11000, 10500, 12000, 11500, 12500, 13000, 12800, 13500, 14000, 14500, 14200, 14800, 15000, 15200, 15500, 15800, 16000, 16200, 16500]
    }
    market_df = pd.DataFrame(data)

    final_signal = get_trading_signal(market_df)
    print(f"\nSignal de trading final calculé : {final_signal:.4f}")
