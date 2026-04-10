FROM python:3.11-slim

# Installation de sqlite3 et autres utilitaires si nécessaire
RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Création du dossier data pour la persistance de la base de données
RUN mkdir -p /app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Commande de lancement
CMD ["python", "main.py"]
