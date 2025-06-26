# Dockerfile pour le bot de trading

# Utiliser une image Python de base
FROM python:3.10-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les dépendances
# Note : l'installation de torch et bitsandbytes peut nécessiter des ajustements
# en fonction de l'architecture cible (CPU/GPU).
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code de l'application
COPY . .

# Créer le répertoire pour les données
RUN mkdir -p /app/data

# Commande pour lancer le bot
CMD ["python", "trading_bot.py"]
