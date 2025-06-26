# Bot de Trading IA

Bot de trading haute fréquence utilisant un modèle IA local, une analyse de sentiment des actualités et des indicateurs techniques pour prendre des décisions.

## Architecture

Le bot est conçu selon une architecture modulaire :
- `trading_bot.py`: Cœur logique et orchestration.
- `market_predictor.py`: Moteur de prédiction (IA + News + Indicateurs).
- `data_handler.py`: Acquisition et gestion des données.
- `discord_reporter.py`: Communication avec Discord.

## Fonctionnalités Clés

- **Modèle IA Local**: Utilise un modèle de type TinyLLaMA/StableLM (≤3B) pour l'analyse prédictive.
- **Signal Hybride**: Combine le score IA, le sentiment des actualités et le RSI.
- **Gestion des Risques**: Stop-Loss (-2%), Take-Profit (ajusté par ATR), Disjoncteur de drawdown (>5%).
- **Journalisation**: Logs des trades au format Parquet.
- **Interface Discord**: Commandes `/status`, `/pause`, `/backtest`.

## Démarrage Rapide (Docker)

1.  **Configurer les variables d'environnement :**
    - Renommez `.env.example` en `.env`.
    - Remplissez les clés d'API (`DISCORD_BOT_TOKEN`, `NEWS_API_KEY`, etc.).

2.  **Construire et lancer le conteneur :**
    ```bash
    docker build -t trading-bot .
    docker run --env-file .env trading-bot
    ```
