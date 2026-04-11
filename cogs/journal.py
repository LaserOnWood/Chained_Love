"""
COG : JOURNAL & STATISTIQUES (Module 5)
Commandes : /checkin, /history, /stats
Loop     : prompt check-in quotidien via DM
"""
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone

from utils import database as db
from utils.embeds import embed, error, success

MOOD_EMOJI = [(8, "🤩"), (6, "😊"), (4, "🙂"), (2, "😐"), (0, "😔")]


def mood_emoji(score: int) -> str:
    for threshold, emoji in MOOD_EMOJI:
        if score > threshold:
            return emoji
    return "😔"


def progress_bar(ratio: float, width: int = 16) -> str:
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


class JournalCog(commands.Cog, name="Journal"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_prompt.start()

    def cog_unload(self):
        self.daily_prompt.cancel()

    @app_commands.command(name="checkin", description="[SUB] Enregistrer ton humeur du jour (1-10).")
    @app_commands.describe(mood="État d'esprit de 1 (difficile) à 10 (excellent)", note="Note libre optionnelle")
    async def checkin(self, interaction: discord.Interaction, mood: int, note: str = ""):
        if not 1 <= mood <= 10:
            await interaction.response.send_message(embed=error("L'humeur doit être entre **1** et **10**."), ephemeral=True)
            return
        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(uid, gid)
        sub_pair = next((p for p in pairs if p["sub_id"] == uid), None)
        if not sub_pair:
            await interaction.response.send_message(
                embed=error("Tu n'as pas de liaison active en tant que subordonné·e."), ephemeral=True
            )
            return
        await db.add_checkin(sub_pair["id"], uid, mood, note or None)
        emoji = mood_emoji(mood)
        await interaction.response.send_message(
            embed=embed(f"{emoji} Check-in enregistré",
                        f"Humeur : **{mood}/10**" + (f"\n_{note}_" if note else ""), color="success"),
            ephemeral=True,
        )
        if mood <= 3:
            try:
                dom = await self.bot.fetch_user(sub_pair["dom_id"])
                await dom.send(embed=embed("⚠️ Humeur basse détectée",
                                           f"{interaction.user.mention} a enregistré un mood de **{mood}/10** {emoji}."
                                           + (f"\n_{note}_" if note else "")
                                           + "\n\nPensez à vérifier son état. 🤍", color="warn"))
            except Exception:
                pass

    @app_commands.command(name="history", description="Historique de tes check-ins (7 derniers jours).")
    async def history(self, interaction: discord.Interaction):
        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(uid, gid)
        sub_pair = next((p for p in pairs if p["sub_id"] == uid), None)
        if not sub_pair:
            await interaction.response.send_message(
                embed=error("Tu n'as pas de liaison active en tant que subordonné·e."), ephemeral=True
            )
            return
        checkins = await db.get_recent_checkins(sub_pair["id"], limit=7)
        if not checkins:
            await interaction.response.send_message(
                embed=embed("📖 Historique", "Aucun check-in trouvé. Utilise `/checkin` chaque jour !", color="info"),
                ephemeral=True,
            )
            return
        lines = []
        for c in checkins:
            date_str = c["checked_at"][:10]  # SQLite renvoie du texte ISO
            note_str = f" – _{c['note']}_" if c["note"] else ""
            lines.append(f"`{date_str}` {mood_emoji(c['mood'])} **{c['mood']}/10**{note_str}")
        avg = round(sum(c["mood"] for c in checkins) / len(checkins), 1)
        await interaction.response.send_message(
            embed=embed("📖 Historique (7 jours)", "\n".join(lines) + f"\n\n**Moyenne : {avg}/10**", color="info"),
            ephemeral=True,
        )

    @app_commands.command(name="sub_history", description="[DOM] Voir l'historique des check-ins de ton/ta subordonné·e.")
    @app_commands.describe(sub="Le/la subordonné·e à consulter")
    async def sub_history(self, interaction: discord.Interaction, sub: discord.Member):
        uid, gid = interaction.user.id, interaction.guild_id
        # Vérifier si l'utilisateur est bien le dominant de ce sub
        pair = await db.get_pair_by_users(uid, sub.id, gid)
        
        if not pair or pair["dom_id"] != uid or pair["sub_id"] != sub.id:
            await interaction.response.send_message(
                embed=error(f"Tu n'as pas de liaison active en tant que dominant·e avec {sub.display_name}."), 
                ephemeral=True
            )
            return
            
        checkins = await db.get_recent_checkins(pair["id"], limit=10)
        if not checkins:
            await interaction.response.send_message(
                embed=embed(f"📖 Historique de {sub.display_name}", "Aucun check-in trouvé pour le moment.", color="info"),
                ephemeral=True,
            )
            return
            
        lines = []
        for c in checkins:
            # Formatage de la date plus lisible
            date_str = c["checked_at"][:16].replace("T", " ")
            note_str = f" – _{c['note']}_" if c["note"] else ""
            lines.append(f"`{date_str}` {mood_emoji(c['mood'])} **{c['mood']}/10**{note_str}")
            
        avg = round(sum(c["mood"] for c in checkins) / len(checkins), 1)
        
        e = discord.Embed(
            title=f"📖 État de {sub.display_name}",
            description="\n".join(lines) + f"\n\n**Moyenne (10 derniers) : {avg}/10**",
            color=0x9B59B6
        )
        e.set_thumbnail(url=sub.display_avatar.url)
        
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="stats", description="Statistiques de la semaine pour ta liaison.")
    @app_commands.describe(partner="Ton/ta partenaire (optionnel)")
    async def stats(self, interaction: discord.Interaction, partner: discord.Member = None):
        uid, gid = interaction.user.id, interaction.guild_id
        pair = None
        if partner:
            pair = await db.get_pair_by_users(uid, partner.id, gid)
        else:
            pairs = await db.get_pairs_for_user(uid, gid)
            pair = pairs[0] if pairs else None
        if not pair:
            await interaction.response.send_message(embed=error("Aucune liaison trouvée."), ephemeral=True)
            return
        s = await db.get_weekly_stats(pair["id"])
        balance = await db.get_balance(pair["id"])
        checkins = await db.get_recent_checkins(pair["id"])
        done = s["done"] or 0
        pending = s["pending"] or 0
        refused = s["refused"] or 0
        total = done + pending + refused
        ratio = done / total if total > 0 else 0
        pct = round(ratio * 100)
        avg_mood = round(sum(c["mood"] for c in checkins) / len(checkins), 1) if checkins else None
        other_id = pair["sub_id"] if pair["dom_id"] == uid else pair["dom_id"]
        e = discord.Embed(title="📊 Statistiques — 7 derniers jours",
                          description=f"Liaison avec <@{other_id}>", color=0x9B59B6)
        e.add_field(name="Tâches complétées",
                    value=f"`{progress_bar(ratio)}` **{pct}%**\n{done} validées / {total} soumises", inline=False)
        e.add_field(name="⏳ En attente", value=str(pending), inline=True)
        e.add_field(name="❌ Refusées",   value=str(refused), inline=True)
        e.add_field(name="💰 Solde",      value=f"{balance} pts", inline=True)
        if avg_mood is not None:
            e.add_field(name="💭 Humeur moyenne", value=f"{mood_emoji(int(avg_mood))} {avg_mood}/10", inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @tasks.loop(hours=1)
    async def daily_prompt(self):
        current_hour = datetime.now(timezone.utc).hour
        try:
            all_pairs = await db.get_all_active_pairs_with_reminders()
        except Exception:
            return
        for p in all_pairs:
            if p["checkin_hour"] != current_hour:
                continue
            try:
                existing = await db.get_today_checkin(p["id"], p["sub_id"])
                if existing:
                    continue
                sub = await self.bot.fetch_user(p["sub_id"])
                await sub.send(embed=embed("🌙 Check-in du soir",
                                           "Comment s'est passée ta journée ?\nUtilise `/checkin <1-10>` pour enregistrer ton humeur.",
                                           color="info"))
            except Exception:
                pass

    @daily_prompt.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(JournalCog(bot))
