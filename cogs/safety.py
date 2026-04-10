"""
COG : SÉCURITÉ & PROTOCOLES (Module 4)
Commandes : /safeword red | yellow, /limit add | remove | view (avec choices Discord)
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils import database as db
from utils.embeds import embed, error, success, warn, COLOR_EMOJI

LIMIT_COLORS = {
    "green":  ("🟢", 0x2ECC71, "Autorisé / apprécié"),
    "orange": ("🟠", 0xF39C12, "À aborder avec précaution"),
    "red":    ("🔴", 0xE74C3C, "Limite absolue – JAMAIS"),
}


class AftercareCancelView(discord.ui.View):
    """Bouton partagé pour résoudre un safeword actif."""

    def __init__(self, event_id: int, pair_id: int, dom_id: int, sub_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.pair_id = pair_id
        self.dom_id = dom_id
        self.sub_id = sub_id

    @discord.ui.button(label="✅ Situation résolue – Reprendre", style=discord.ButtonStyle.success)
    async def resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.dom_id, self.sub_id):
            await interaction.response.send_message("Seuls les partenaires peuvent résoudre.", ephemeral=True)
            return
        await db.resolve_safeword(interaction.client.pool, self.event_id)
        await db.set_reminders(interaction.client.pool, self.pair_id, True)
        self.stop()
        await interaction.response.edit_message(
            embed=success("✅ Safeword résolu. Les notifications reprennent normalement."),
            view=None,
        )


class SafetyCog(commands.Cog, name="Safety"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /safeword ──────────────────────────────────────────────────────────────
    safeword_group = app_commands.Group(name="safeword", description="Commandes de sécurité.")

    @safeword_group.command(name="red", description="🔴 ARRÊT TOTAL — Stoppe immédiatement toutes les activités.")
    async def safeword_red(self, interaction: discord.Interaction):
        pairs = await db.get_pairs_for_user(self.bot.pool, interaction.user.id, interaction.guild_id)
        if not pairs:
            await interaction.response.send_message(embed=error("Aucune liaison active trouvée."), ephemeral=True)
            return

        pair = pairs[0]
        event_id = await db.log_safeword(self.bot.pool, pair["id"], interaction.user.id, "RED")
        await db.set_reminders(self.bot.pool, pair["id"], False)

        dom_id, sub_id = pair["dom_id"], pair["sub_id"]
        other_id = sub_id if interaction.user.id == dom_id else dom_id

        view = AftercareCancelView(event_id=event_id, pair_id=pair["id"], dom_id=dom_id, sub_id=sub_id)
        emergency_embed = discord.Embed(
            title="🚨 SAFEWORD RED — ARRÊT IMMÉDIAT",
            description=(
                f"**{interaction.user.mention} a déclenché le safeword RED.**\n\n"
                "Toutes les activités, tâches et notifications sont **immédiatement suspendues**.\n\n"
                "Prenez soin l'un·e de l'autre. 🤍\n\n"
                "_Cliquez sur le bouton ci-dessous une fois la situation résolue._"
            ),
            color=0xFF0000,
        )

        try:
            other = await self.bot.fetch_user(other_id)
            await other.send(
                embed=emergency_embed,
                view=AftercareCancelView(event_id, pair["id"], dom_id, sub_id),
            )
        except Exception:
            pass

        await interaction.response.send_message(embed=emergency_embed, view=view)

    @safeword_group.command(name="yellow", description="🟡 PAUSE — Demande une pause et ouvre l'aftercare.")
    async def safeword_yellow(self, interaction: discord.Interaction):
        pairs = await db.get_pairs_for_user(self.bot.pool, interaction.user.id, interaction.guild_id)
        if not pairs:
            await interaction.response.send_message(embed=error("Aucune liaison active trouvée."), ephemeral=True)
            return

        pair = pairs[0]
        event_id = await db.log_safeword(self.bot.pool, pair["id"], interaction.user.id, "YELLOW")
        await db.set_reminders(self.bot.pool, pair["id"], False)

        dom_id, sub_id = pair["dom_id"], pair["sub_id"]
        other_id = sub_id if interaction.user.id == dom_id else dom_id

        view = AftercareCancelView(event_id=event_id, pair_id=pair["id"], dom_id=dom_id, sub_id=sub_id)
        pause_embed = discord.Embed(
            title="🟡 SAFEWORD YELLOW — PAUSE",
            description=(
                f"**{interaction.user.mention} demande une pause.**\n\n"
                "Les notifications sont temporairement suspendues.\n"
                "Prenez le temps de communiquer. 💛\n\n"
                "_Cliquez sur le bouton ci-dessous pour reprendre._"
            ),
            color=0xF39C12,
        )

        # Création automatique du canal #aftercare si absent
        guild = interaction.guild
        aftercare_ch = discord.utils.get(guild.text_channels, name="aftercare")
        if not aftercare_ch:
            try:
                aftercare_ch = await guild.create_text_channel(
                    "aftercare", topic="Espace sécurisé. 🤍", reason="Safeword YELLOW déclenché"
                )
            except discord.Forbidden:
                pass

        if aftercare_ch:
            dom_user = guild.get_member(dom_id)
            sub_user = guild.get_member(sub_id)
            mentions = " ".join(m.mention for m in [dom_user, sub_user] if m)
            await aftercare_ch.send(
                content=mentions,
                embed=embed(
                    "🟡 Espace Aftercare",
                    "Un safeword YELLOW a été utilisé. Prenez le temps qu'il faut. 🤍",
                    color="warn",
                ),
            )

        try:
            other = await self.bot.fetch_user(other_id)
            await other.send(
                embed=pause_embed,
                view=AftercareCancelView(event_id, pair["id"], dom_id, sub_id),
            )
        except Exception:
            pass

        await interaction.response.send_message(embed=pause_embed, view=view)

    # ── /limit ────────────────────────────────────────────────────────────────
    limit_group = app_commands.Group(name="limit", description="Gérer le registre des limites.")

    @limit_group.command(name="add", description="Ajouter une limite au registre partagé.")
    @app_commands.describe(label="Nom de la limite", color="Niveau de la limite", notes="Notes optionnelles")
    @app_commands.choices(color=[
        app_commands.Choice(name="🟢 Vert — Autorisé / apprécié",            value="green"),
        app_commands.Choice(name="🟠 Orange — À aborder avec précaution",     value="orange"),
        app_commands.Choice(name="🔴 Rouge — Limite absolue (JAMAIS)",        value="red"),
    ])
    async def limit_add(self, interaction: discord.Interaction, label: str, color: str, notes: str = ""):
        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
        if not pairs:
            await interaction.response.send_message(embed=error("Aucune liaison active."), ephemeral=True)
            return

        pair = pairs[0]
        lid = await db.add_limit(self.bot.pool, pair["id"], label, color, notes or None, uid)
        emoji_icon, clr, _ = LIMIT_COLORS[color]

        e = discord.Embed(
            title=f"{emoji_icon} Limite ajoutée",
            description=f"**{label}**" + (f"\n_{notes}_" if notes else ""),
            color=clr,
        )
        e.set_footer(text=f"ID #{lid}")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @limit_group.command(name="remove", description="Supprimer une limite du registre.")
    @app_commands.describe(limit_id="ID de la limite à supprimer")
    async def limit_remove(self, interaction: discord.Interaction, limit_id: int):
        uid, gid = interaction.user.id, interaction.guild_id
        pairs = await db.get_pairs_for_user(self.bot.pool, uid, gid)
        pair_ids = {p["id"] for p in pairs}

        async with self.bot.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM limits WHERE id=$1", limit_id)

        if not row or row["pair_id"] not in pair_ids:
            await interaction.response.send_message(embed=error("Limite introuvable ou accès refusé."), ephemeral=True)
            return

        await db.delete_limit(self.bot.pool, limit_id)
        await interaction.response.send_message(
            embed=warn(f"Limite **{row['name']}** supprimée."), ephemeral=True
        )

    @app_commands.command(name="limits", description="Consulter le registre des limites de ta liaison.")
    @app_commands.describe(partner="Ton/ta partenaire (optionnel)")
    async def limits_view(self, interaction: discord.Interaction, partner: discord.Member = None):
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

        limits = await db.get_limits(self.bot.pool, pair["id"])
        other_id = pair["sub_id"] if pair["dom_id"] == uid else pair["dom_id"]

        e = discord.Embed(
            title="📋 Registre des Limites",
            description=f"Liaison avec <@{other_id}>",
            color=0x9B59B6,
        )

        if not limits:
            e.description += "\n\nAucune limite enregistrée. Utilise `/limit add`."
        else:
            for color_key, (emoji_icon, clr, desc) in LIMIT_COLORS.items():
                group = [l for l in limits if l["color"] == color_key]
                if group:
                    lines = [
                        f"`#{l['id']}` **{l['name']}**" + (f"\n  _{l['description']}_" if l["description"] else "")
                        for l in group
                    ]
                    e.add_field(name=f"{emoji_icon} {desc}", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SafetyCog(bot))
