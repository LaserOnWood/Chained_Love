"""
COG : ÉCONOMIE DE POUVOIR (Module 3)
Commandes : /wallet, /shop add | list, /buy
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils import database as db
from utils.embeds import embed, error, success


class ShopView(discord.ui.View):
    def __init__(self, items, pair_id: int, sub_id: int):
        super().__init__(timeout=60)
        self.items = items
        self.pair_id = pair_id
        self.sub_id = sub_id

        options = [
            discord.SelectOption(
                label=f"{it['name']} — {it['cost']} pts",
                description=it["description"] or "",
                value=str(it["id"]),
            )
            for it in items
        ]
        select = discord.ui.Select(placeholder="Choisir une récompense…", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sub_id:
            await interaction.response.send_message("Seul·e le/la subordonné·e peut acheter.", ephemeral=True)
            return
        item_id = int(interaction.data["values"][0])
        item = next(it for it in self.items if it["id"] == item_id)
        balance = await db.get_balance(self.pair_id)
        if balance < item["cost"]:
            await interaction.response.send_message(
                embed=error(f"Solde insuffisant : {balance} pts / {item['cost']} pts requis."), ephemeral=True
            )
            return
        purchase_id = await db.create_purchase(item_id, self.pair_id)
        pair = await db.get_pair(self.pair_id)
        view = PurchaseValidateView(purchase_id=purchase_id, item=item, pair_id=self.pair_id, sub_id=self.sub_id)
        notif = embed("🛍️ Demande de récompense",
                      f"<@{self.sub_id}> souhaite obtenir **{item['name']}** ({item['cost']} pts).", color="info")
        try:
            dom = await interaction.client.fetch_user(pair["dom_id"])
            await dom.send(embed=notif, view=view)
            dm_ok = True
        except Exception:
            dm_ok = False
        self.stop()
        await interaction.response.edit_message(
            embed=embed("⏳ Demande envoyée",
                        f"Récompense **{item['name']}** en attente de validation."
                        + ("\n✉️ Ton/Ta Dominant·e a été notifié·e." if dm_ok else ""), color="ok"),
            view=None,
        )


class PurchaseValidateView(discord.ui.View):
    def __init__(self, purchase_id: int, item: dict, pair_id: int, sub_id: int):
        super().__init__(timeout=86400)
        self.purchase_id = purchase_id
        self.item = item
        self.pair_id = pair_id
        self.sub_id = sub_id

    @discord.ui.button(label="✅ Accorder", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        pair = await db.get_pair(self.pair_id)
        if interaction.user.id != pair["dom_id"]:
            await interaction.response.send_message("Seul·e le/la Dominant·e peut valider.", ephemeral=True)
            return
        ok = await db.deduct_points(self.pair_id, self.item["cost"])
        if not ok:
            await interaction.response.send_message(embed=error("Solde insuffisant."), ephemeral=True)
            return
        await db.validate_purchase(self.purchase_id, True)
        self.stop()
        await interaction.response.edit_message(
            embed=success(f"Récompense **{self.item['name']}** accordée à <@{self.sub_id}>.\n—{self.item['cost']} pts déduits."),
            view=None,
        )

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        pair = await db.get_pair(self.pair_id)
        if interaction.user.id != pair["dom_id"]:
            await interaction.response.send_message("Seul·e le/la Dominant·e peut refuser.", ephemeral=True)
            return
        await db.validate_purchase(self.purchase_id, False)
        self.stop()
        await interaction.response.edit_message(
            embed=embed("❌ Récompense refusée", f"La demande de <@{self.sub_id}> a été refusée.", color="error"),
            view=None,
        )


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="wallet", description="Affiche le solde de points de ta liaison.")
    @app_commands.describe(partner="Ton/ta partenaire (optionnel)")
    async def wallet(self, interaction: discord.Interaction, partner: discord.Member = None):
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
        balance = await db.get_balance(pair["id"])
        other_id = pair["sub_id"] if pair["dom_id"] == uid else pair["dom_id"]
        await interaction.response.send_message(
            embed=embed("💰 Portefeuille",
                        f"Liaison avec <@{other_id}> (paire `#{pair['id']}`)\n\n**{balance} pts** disponibles",
                        color="ok"),
            ephemeral=True,
        )

    shop_group = app_commands.Group(name="shop", description="Boutique de récompenses")

    @shop_group.command(name="add", description="[DOM] Ajoute une récompense à la boutique.")
    @app_commands.describe(sub="Le/la subordonné·e", name="Nom de la récompense",
                           cost="Coût en points", description="Description optionnelle")
    async def shop_add(self, interaction: discord.Interaction, sub: discord.Member,
                       name: str, cost: int = 50, description: str = ""):
        pair = await db.get_pair_by_users(interaction.user.id, sub.id, interaction.guild_id)
        if not pair or pair["dom_id"] != interaction.user.id:
            await interaction.response.send_message(
                embed=error("Tu n'es pas le/la Dominant·e de cette liaison."), ephemeral=True
            )
            return
        iid = await db.create_shop_item(pair["id"], name, description, cost)
        await interaction.response.send_message(
            embed=success(f"Récompense **{name}** ajoutée (ID `#{iid}`) pour {cost} pts.")
        )

    @shop_group.command(name="list", description="Affiche la boutique de ta liaison.")
    @app_commands.describe(partner="Ton/ta partenaire (optionnel)")
    async def shop_list(self, interaction: discord.Interaction, partner: discord.Member = None):
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
        items = await db.get_shop_items(pair["id"])
        if not items:
            await interaction.response.send_message(
                embed=embed("🛍️ Boutique", "Aucun item disponible.", color="info"), ephemeral=True
            )
            return
        lines = [f"`#{it['id']}` **{it['name']}** — {it['cost']} pts\n  _{it['description'] or ''}_" for it in items]
        await interaction.response.send_message(
            embed=embed("🛍️ Boutique", "\n".join(lines), color="ok"), ephemeral=True
        )

    @app_commands.command(name="buy", description="[SUB] Ouvre la boutique pour acheter une récompense.")
    @app_commands.describe(partner="Ton/ta Dominant·e (optionnel)")
    async def buy(self, interaction: discord.Interaction, partner: discord.Member = None):
        uid, gid = interaction.user.id, interaction.guild_id
        pair = None
        if partner:
            pair = await db.get_pair_by_users(uid, partner.id, gid)
        else:
            pairs = await db.get_pairs_for_user(uid, gid)
            pair = pairs[0] if pairs else None
        if not pair or pair["sub_id"] != uid:
            await interaction.response.send_message(
                embed=error("Tu n'es pas subordonné·e dans cette liaison."), ephemeral=True
            )
            return
        items = await db.get_shop_items(pair["id"])
        if not items:
            await interaction.response.send_message(
                embed=embed("🛍️ Boutique vide", "Aucun item disponible.", color="info"), ephemeral=True
            )
            return
        balance = await db.get_balance(pair["id"])
        view = ShopView(items=items, pair_id=pair["id"], sub_id=uid)
        await interaction.response.send_message(
            embed=embed("🛍️ Boutique", f"Solde actuel : **{balance} pts**\nSélectionne une récompense :", color="ok"),
            view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
