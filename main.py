"""
Chained_Love — Bot Discord
Point d'entrée principal.

Variables d'environnement :
  DISCORD_TOKEN  – Token du bot Discord (obligatoire)
  DB_PATH        – Chemin vers le fichier SQLite (défaut : ./chained_love.db)
"""
import asyncio
import logging
import os

import discord
from discord.ext import commands

from utils.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("chained_love")

COGS = [
    "cogs.pairing",   # Module 1 – Liaisons
    "cogs.tasks",     # Module 2 – Tâches & routines
    "cogs.economy",   # Module 3 – Points & boutique
    "cogs.safety",    # Module 4 – Safewords & limites
    "cogs.journal",   # Module 5 – Journal, check-ins, stats
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class ChainedLove(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        log.info(f"Base de données : {os.environ.get('DB_PATH', 'chained_love.db')}")
        await init_db()
        log.info("Schéma SQLite initialisé.")

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Cog chargé : {cog}")
            except Exception as e:
                log.error(f"Erreur chargement {cog} : {e}", exc_info=True)

        await self.tree.sync()
        log.info("Slash commands synchronisées.")

    async def on_ready(self):
        log.info(f"Bot connecté : {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="les liaisons 🔗")
        )

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"Erreur slash command : {error}", exc_info=True)
        try:
            await interaction.response.send_message(
                "Une erreur interne s'est produite. Contacte l'administrateur.", ephemeral=True
            )
        except Exception:
            pass


async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Variable d'environnement DISCORD_TOKEN manquante.")
    bot = ChainedLove()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
