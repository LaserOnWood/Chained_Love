"""
COG : DISCIPLINE & ROUTINES (Module 2)
Commandes : /task add | list | delete, /done
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import database as db
from utils.embeds import embed, error, success, warn

RECURRENCES = ["daily", "weekly", "none"]


def _task_list_embed(task_list, title="📋 Tâches actives"):
    if not task_list:
        return embed(title, "Aucune tâche définie.", color="info")
    lines = []
    for t in task_list:
        proof = " 📷" if t["requires_proof"] else ""
        lines.append(
            f"`#{t['id']}` **{t['name']}** — {t['points']} pts · *{t['recurrence']}*{proof}\n"
            f"  _{t['description'] or 'Pas de description'}_"
        )
    return embed(title, "\n".join(lines), color="info")


class ValidateView(discord.ui.View):
    """Boutons DOM : Valider / Refuser une completion."""

    def __init__(self, completion_id: int, pair_id: int, task_points: int, sub_id: int):
        super().__init__(timeout=86400)
        self.completion_id = completion_id
        self.pair_id = pair_id
        self.task_points = task_points
        self.sub_id = sub_id

    @discord.ui.button(label="✅ Valider", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        pair = await db.get_pair(interaction.client.pool, self.pair_id)
        if interaction.user.id != pair["dom_id"]:
            await interaction.response.send_message("Seul·e le/la Dominant·e peut valider.", ephemeral=True)
            return
        await db.validate_completion(interaction.client.pool, self.completion_id, True)
        await db.add_points(interaction.client.pool, self.pair_id, self.task_points)
        self.stop()
        await interaction.response.edit_message(
            embed=success(f"Tâche validée ✅ — **+{self.task_points} pts** accordés à <@{self.sub_id}>"),
            view=None,
        )

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        pair = await db.get_pair(interaction.client.pool, self.pair_id)
        if interaction.user.id != pair["dom_id"]:
            await interaction.response.send_message("Seul·e le/la Dominant·e peut refuser.", ephemeral=True)
            return
        await db.validate_completion(interaction.client.pool, self.completion_id, False)
        self.stop()
        await interaction.response.edit_message(
            embed=embed("❌ Tâche refusée", f"La completion de <@{self.sub_id}> a été refusée.", color="error"),
            view=None,
        )


class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    task_group = app_commands.Group(name="task", description="Gestion des tâches")

    @task_group.command(name="add", description="[DOM] Crée une tâche pour un/e subordonné/e.")
    @app_commands.describe(
        sub="Le/la subordonné·e concerné·e",
        name="Nom de la tâche",
        points="Points accordés à la validation",
        recurrence="Fréquence : daily | weekly | none",
        description="Description optionnelle",
        requires_proof="Preuve photo obligatoire ?",
    )
    async def task_add(
        self,
        interaction: discord.Interaction,
        sub: discord.Member,
        name: str,
        points: int = 10,
        recurrence: str = "daily",
        description: str = "",
        requires_proof: bool = False,
    ):
        if recurrence not in RECURRENCES:
            await interaction.response.send_message(
                embed=error(f"Récurrence invalide. Choix : {', '.join(RECURRENCES)}"), ephemeral=True
            )
            return

        pair = await db.get_pair_by_users(self.bot.pool, interaction.user.id, sub.id, interaction.guild_id)
        if not pair or pair["dom_id"] != interaction.user.id:
            await interaction.response.send_message(
                embed=error("Tu n'es pas le/la Dominant·e de cette liaison."), ephemeral=True
            )
            return

        tid = await db.create_task(
            self.bot.pool, pair["id"], name, description, points, recurrence, requires_proof
        )
        await interaction.response.send_message(
            embed=success(
                f"Tâche **{name}** créée (ID `#{tid}`) pour {sub.mention}.\n"
                f"{points} pts · {recurrence} · Preuve : {'oui 📷' if requires_proof else 'non'}"
            )
        )

    @task_group.command(name="list", description="Affiche les tâches de ta liaison.")
    @app_commands.describe(sub="Le/la subordonné·e (optionnel si tu es SUB toi-même)")
    async def task_list(self, interaction: discord.Interaction, sub: discord.Member = None):
        uid, gid = interaction.user.id, interaction.guild_id
        pair = None
        if sub:
            pair = await db.get_pair_by_users(self.bot.pool, uid, sub.id, gid)
        else:
            pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
            pair = pairs[0] if pairs else None

        if not pair:
            await interaction.response.send_message(embed=error("Aucune liaison trouvée."), ephemeral=True)
            return

        task_list = await db.get_tasks(self.bot.pool, pair["id"])
        await interaction.response.send_message(embed=_task_list_embed(task_list), ephemeral=True)

    @task_group.command(name="delete", description="[DOM] Supprime une tâche.")
    @app_commands.describe(task_id="ID de la tâche à supprimer")
    async def task_delete(self, interaction: discord.Interaction, task_id: int):
        task = await db.get_task(self.bot.pool, task_id)
        if not task:
            await interaction.response.send_message(embed=error("Tâche introuvable."), ephemeral=True)
            return
        pair = await db.get_pair(self.bot.pool, task["pair_id"])
        if pair["dom_id"] != interaction.user.id:
            await interaction.response.send_message(embed=error("Accès refusé."), ephemeral=True)
            return
        await db.delete_task(self.bot.pool, task_id)
        await interaction.response.send_message(embed=success(f"Tâche `#{task_id}` supprimée."))

    @app_commands.command(name="done", description="[SUB] Déclare une tâche accomplie.")
    @app_commands.describe(task_id="ID de la tâche accomplie")
    async def done(self, interaction: discord.Interaction, task_id: int):
        task = await db.get_task(self.bot.pool, task_id)
        if not task:
            await interaction.response.send_message(embed=error("Tâche introuvable."), ephemeral=True)
            return

        pair = await db.get_pair(self.bot.pool, task["pair_id"])
        if pair["sub_id"] != interaction.user.id:
            await interaction.response.send_message(
                embed=error("Cette tâche ne t'appartient pas."), ephemeral=True
            )
            return

        sw = await db.get_active_safeword(self.bot.pool, pair["id"])
        if sw:
            await interaction.response.send_message(
                embed=error("Un safeword est actif. Les tâches sont suspendues."), ephemeral=True
            )
            return

        proof_url = None

        if task["requires_proof"]:
            await interaction.response.send_message(
                embed=embed(
                    "📷 Preuve requise",
                    "Envoie ta photo/vidéo dans ce canal dans les **2 minutes**.",
                    color="warn",
                )
            )

            def check(m: discord.Message):
                return (
                    m.author.id == interaction.user.id
                    and m.channel.id == interaction.channel_id
                    and len(m.attachments) > 0
                )

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=120)
                proof_url = msg.attachments[0].url
            except asyncio.TimeoutError:
                await interaction.followup.send(embed=error("Temps écoulé. Aucune preuve reçue."))
                return
        else:
            await interaction.response.defer()

        completion_id = await db.add_completion(self.bot.pool, task_id, pair["id"], proof_url)

        view = ValidateView(
            completion_id=completion_id,
            pair_id=pair["id"],
            task_points=task["points"],
            sub_id=interaction.user.id,
        )
        notif_embed = embed(
            "📬 Validation en attente",
            f"<@{interaction.user.id}> a complété **{task['name']}**.\n"
            + (f"[Voir la preuve]({proof_url})" if proof_url else ""),
            color="info",
        )

        try:
            dom = await self.bot.fetch_user(pair["dom_id"])
            await dom.send(embed=notif_embed, view=view)
            dom_notified = True
        except Exception:
            dom_notified = False

        confirm = embed(
            "⏳ En attente de validation",
            f"Tâche **{task['name']}** soumise."
            + ("\n✉️ Ton/Ta Dominant·e a été notifié·e." if dom_notified else ""),
            color="ok",
        )
        await interaction.followup.send(embed=confirm)

    @tasks.loop(hours=1)
    async def reminder_loop(self):
        from datetime import datetime, timezone
        current_hour = datetime.now(timezone.utc).hour
        try:
            all_pairs = await db.get_all_active_pairs_with_reminders(self.bot.pool)
        except Exception:
            return
        for p in all_pairs:
            if p["checkin_hour"] != current_hour:
                continue
            try:
                task_list = await db.get_tasks(self.bot.pool, p["id"])
                if not task_list:
                    continue
                sub = await self.bot.fetch_user(p["sub_id"])
                lines = "\n".join(f"• `#{t['id']}` {t['name']}" for t in task_list)
                await sub.send(
                    embed=embed("⏰ Rappel quotidien", f"N'oublie pas tes tâches du jour :\n{lines}", color="info")
                )
            except Exception:
                pass

    @reminder_loop.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TasksCog(bot))
