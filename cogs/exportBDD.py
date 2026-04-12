import discord
from discord.ext import commands
from discord import app_commands
import os
import zipfile
import datetime

from utils.database import DB_PATH  # ← source unique du chemin


class ExportBDD(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="export_bdd", description="Exporte et compresse la base de données (Propriétaire du bot uniquement)")
    async def export_bdd(self, interaction: discord.Interaction):
        # Vérification : propriétaire du bot uniquement
        if not await self.bot.is_owner(interaction.user):
            embed = discord.Embed(
                title="❌ Accès refusé",
                description="Seul le propriétaire du bot peut exporter la base de données.",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not os.path.exists(DB_PATH):
            embed = discord.Embed(
                title="❌ Erreur",
                description=f"Fichier de base de données introuvable : `{DB_PATH}`",
                color=0xE74C3C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            file_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            limit_mb = 24  # Marge de sécurité par rapport aux 25 Mo de Discord

            if file_size_mb > limit_mb:
                zip_name = f"backup_db_{datetime.date.today()}.zip"
                with zipfile.ZipFile(zip_name, "w") as zipf:
                    zipf.write(DB_PATH, arcname=os.path.basename(DB_PATH))

                await interaction.followup.send(
                    content=f"📦 Base trop lourde ({file_size_mb:.2f} MB), voici la version compressée.",
                    file=discord.File(zip_name)
                )
                os.remove(zip_name)
            else:
                await interaction.followup.send(content="📄 Voici l'export de la base de données :",
                    file=discord.File(DB_PATH)
                )

        except Exception as e:
            await interaction.followup.send(f"⚠️ Une erreur est survenue : {e}")

async def setup(bot):
    await bot.add_cog(ExportBDD(bot))