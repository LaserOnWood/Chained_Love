"""
COG : JOURNAL & STATISTIQUES (Module 5)
Commandes : /checkin, /history, /stats (override economy.py)
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

    # ── /checkin ──────────────────────────────────────────────────────────────
    @app_commands.command(name="checkin", description="[SUB] Enregistrer ton humeur du jour (1-10).")
    @app_commands.describe(mood="État d'esprit de 1 (difficile) à 10 (excellent)", note="Note libre optionnelle")
    async def checkin(self, interaction: discord.Interaction, mood: int, note: str = ""):
        if not 1 <= mood <= 10:
            await interaction.response.send_message(
                embed=error("L'humeur doit être entre **1** et **10**."), ephemeral=True
            )
            return

        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
        sub_pair = next((p for p in pairs if p["sub_id"] == uid), None)

        if not sub_pair:
            await interaction.response.send_message(
                embed=error("Tu n'as pas de liaison active en tant que subordonné·e."), ephemeral=True
            )
            return

        await db.add_checkin(self.bot.pool, sub_pair["id"], uid, mood, note or None)

        emoji = mood_emoji(mood)
        response_embed = embed(
            f"{emoji} Check-in enregistré",
            f"Humeur : **{mood}/10**" + (f"\n_{note}_" if note else ""),
            color="success",
        )
        await interaction.response.send_message(embed=response_embed, ephemeral=True)

        # Alerte DOM si humeur basse
        if mood <= 3:
            try:
                dom = await self.bot.fetch_user(sub_pair["dom_id"])
                await dom.send(
                    embed=embed(
                        "⚠️ Humeur basse détectée",
                        f"{interaction.user.mention} a enregistré un mood de **{mood}/10** {emoji}."
                        + (f"\n_{note}_" if note else "")
                        + "\n\nPensez à vérifier son état. 🤍",
                        color="warn",
                    )
                )
            except Exception:
                pass

    # ── /history ──────────────────────────────────────────────────────────────
    @app_commands.command(name="history", description="Historique de tes check-ins (7 derniers jours).")
    async def history(self, interaction: discord.Interaction):
        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
        sub_pair = next((p for p in pairs if p["sub_id"] == uid), None)

        if not sub_pair:
            await interaction.response.send_message(
                embed=error("Tu n'as pas de liaison active en tant que subordonné·e."), ephemeral=True
            )
            return

        checkins = await db.get_recent_checkins(self.bot.pool, sub_pair["id"], limit=7)

        if not checkins:
            await interaction.response.send_message(
                embed=embed("📖 Historique", "Aucun check-in trouvé. Utilise `/checkin` chaque jour !", color="info"),
                ephemeral=True,
            )
            return

        lines = []
        for c in checkins:
            date_str = c["checked_at"].strftime("%d/%m")
            note_str = f" – _{c['note']}_" if c["note"] else ""
            lines.append(f"`{date_str}` {mood_emoji(c['mood'])} **{c['mood']}/10**{note_str}")

        avg = round(sum(c["mood"] for c in checkins) / len(checkins), 1)
        await interaction.response.send_message(
            embed=embed(
                "📖 Historique (7 jours)",
                "\n".join(lines) + f"\n\n**Moyenne : {avg}/10**",
                color="info",
            ),
            ephemeral=True,
        )

    # ── /stats ────────────────────────────────────────────────────────────────
    @app_commands.command(name="stats", description="Statistiques de la semaine pour ta liaison.")
    @app_commands.describe(partner="Ton/ta partenaire (optionnel)")
    async def stats(self, interaction: discord.Interaction, partner: discord.Member = None):
        uid, gid = interaction.user.id, interaction.guild_id
        pair = None
        if partner:
            pair = await db.get_pair_by_users(self.bot.pool, uid, partner.id, gid)
        else:
            pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
            pair = pairs[0] if pairs else None

        if not pair:
            await interaction.response.send_message(embed=error("Aucune liaison trouvée."), ephemeral=True)
            return

        s = await db.get_weekly_stats(self.bot.pool, pair["id"])
        balance = await db.get_balance(self.bot.pool, pair["id"])
        checkins = await db.get_recent_checkins(self.bot.pool, pair["id"])

        done = s["done"] or 0
        pending = s["pending"] or 0
        refused = s["refused"] or 0
        total = done + pending + refused
        ratio = done / total if total > 0 else 0
        pct = round(ratio * 100)
        avg_mood = round(sum(c["mood"] for c in checkins) / len(checkins), 1) if checkins else None

        other_id = pair["sub_id"] if pair["dom_id"] == uid else pair["dom_id"]
        bar_str = f"`{progress_bar(ratio)}` **{pct}%**"

        e = discord.Embed(
            title="📊 Statistiques — 7 derniers jours",
            description=f"Liaison avec <@{other_id}>",
            color=0x9B59B6,
        )
        e.add_field(name="Tâches complétées", value=f"{bar_str}\n{done} validées / {total} soumises", inline=False)
        e.add_field(name="⏳ En attente", value=str(pending), inline=True)
        e.add_field(name="❌ Refusées", value=str(refused), inline=True)
        e.add_field(name="💰 Solde", value=f"{balance} pts", inline=True)
        if avg_mood is not None:
            e.add_field(name="💭 Humeur moyenne", value=f"{mood_emoji(int(avg_mood))} {avg_mood}/10", inline=True)

        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── Loop : prompt check-in quotidien ─────────────────────────────────────
    @tasks.loop(hours=24)
    async def daily_prompt(self):
        """Chaque soir, rappel aux subs qui n'ont pas encore fait leur check-in."""
        try:
            all_pairs = await db.get_all_active_pairs_with_reminders(self.bot.pool)
        except Exception:
            return

        now_hour = datetime.now(timezone.utc).hour

        for p in all_pairs:
            if p["checkin_hour"] != now_hour:
                continue
            try:
                recent = await db.get_recent_checkins(self.bot.pool, p["id"], limit=1)
                if recent:
                    last = recent[0]["checked_at"]
                    if last.date() == datetime.now(timezone.utc).date():
                        continue  # déjà fait aujourd'hui

                sub = await self.bot.fetch_user(p["sub_id"])
                await sub.send(
                    embed=embed(
                        "🌙 Check-in du soir",
                        "Comment s'est passée ta journée ?\nUtilise `/checkin <1-10>` pour enregistrer ton humeur.",
                        color="info",
                    )
                )
            except Exception:
                pass

    @daily_prompt.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(JournalCog(bot))
