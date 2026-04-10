"""
COG : SYSTÈME DE LIAISON (Module 1)
Commandes : /pair, /unpair, /mypairs
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils import database as db
from utils.embeds import embed, error, success


class PairView(discord.ui.View):
    def __init__(self, dom: discord.Member, sub: discord.Member, dom_label: str, sub_label: str):
        super().__init__(timeout=120)
        self.dom = dom
        self.sub = sub
        self.dom_label = dom_label
        self.sub_label = sub_label

    @discord.ui.button(label="✅ Accepter le contrat", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sub.id:
            await interaction.response.send_message("Seul·e le/la subordonné·e peut accepter.", ephemeral=True)
            return

        pair_id = await db.create_pair(self.dom.id, self.sub.id, interaction.guild_id)

        for label, member in [(self.dom_label, self.dom), (self.sub_label, self.sub)]:
            role = discord.utils.get(interaction.guild.roles, name=label)
            if role:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    pass

        self.stop()
        await interaction.response.edit_message(
            embed=embed(
                "🔗 Liaison établie",
                f"**{self.dom.mention}** ({self.dom_label}) ↔ **{self.sub.mention}** ({self.sub_label})\n"
                f"ID de la paire : `{pair_id}`",
                color="success",
            ),
            view=None,
        )

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sub.id:
            await interaction.response.send_message("Seul·e le/la subordonné·e peut refuser.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            embed=error("La demande de liaison a été refusée."), view=None
        )


class Pairing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pair", description="Propose une liaison à un·e autre utilisateur·rice.")
    @app_commands.describe(
        sub="Le/la subordonné·e à lier",
        dom_label="Titre du Dominant (défaut : Dominant)",
        sub_label="Titre du Subordonné (défaut : Subordonné)",
    )
    async def pair(self, interaction: discord.Interaction, sub: discord.Member,
                   dom_label: str = "Dominant", sub_label: str = "Subordonné"):
        if sub.id == interaction.user.id:
            await interaction.response.send_message(embed=error("Tu ne peux pas te lier à toi-même."), ephemeral=True)
            return
        if sub.bot:
            await interaction.response.send_message(embed=error("Impossible de se lier à un bot."), ephemeral=True)
            return

        existing = await db.get_pair_by_users(interaction.user.id, sub.id, interaction.guild_id)
        if existing:
            await interaction.response.send_message(
                embed=error("Une liaison active existe déjà entre vous deux."), ephemeral=True
            )
            return

        view = PairView(dom=interaction.user, sub=sub, dom_label=dom_label, sub_label=sub_label)
        await interaction.response.send_message(
            content=sub.mention,
            embed=embed(
                "📜 Demande de liaison",
                f"**{interaction.user.mention}** ({dom_label}) souhaite établir un contrat avec toi.\n\n"
                f"En acceptant, tu rejoins la relation en tant que **{sub_label}**.",
                color="info",
            ),
            view=view,
        )

    @app_commands.command(name="unpair", description="Dissout une liaison active.")
    @app_commands.describe(partner="Le/la partenaire avec qui dissoudre la liaison.")
    async def unpair(self, interaction: discord.Interaction, partner: discord.Member):
        pair = await db.get_pair_by_users(interaction.user.id, partner.id, interaction.guild_id)
        if not pair:
            await interaction.response.send_message(embed=error("Aucune liaison active trouvée."), ephemeral=True)
            return
        await db.dissolve_pair(pair["id"])
        await interaction.response.send_message(
            embed=embed("🔓 Liaison dissoute", f"La relation avec {partner.mention} a été fermée.", color="warn")
        )

    @app_commands.command(name="mypairs", description="Affiche tes liaisons actives.")
    async def mypairs(self, interaction: discord.Interaction):
        pairs = await db.get_pairs_for_user(interaction.user.id, interaction.guild_id)
        if not pairs:
            await interaction.response.send_message(embed=error("Tu n'as aucune liaison active."), ephemeral=True)
            return

        lines = []
        for p in pairs:
            role = "DOM" if p["dom_id"] == interaction.user.id else "SUB"
            partner_id = p["sub_id"] if role == "DOM" else p["dom_id"]
            lines.append(f"`#{p['id']}` — <@{partner_id}> · Rôle : **{role}**")

        await interaction.response.send_message(
            embed=embed("🔗 Mes liaisons", "\n".join(lines), color="info"), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Pairing(bot))
