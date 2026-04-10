"""Utilitaires d'embeds Discord réutilisables."""
import discord


COLORS = {
    "ok":      0x9B59B6,   # violet
    "error":   0xE74C3C,   # rouge
    "warn":    0xF39C12,   # orange
    "info":    0x3498DB,   # bleu
    "success": 0x2ECC71,   # vert
    "danger":  0xFF0000,   # rouge vif (safeword RED)
}

COLOR_EMOJI = {"green": "🟢", "orange": "🟠", "red": "🔴"}


def embed(title: str, description: str = "", color: str = "ok", **fields) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=COLORS.get(color, 0x9B59B6))
    for name, value in fields.items():
        e.add_field(name=name, value=str(value), inline=False)
    return e


def error(msg: str) -> discord.Embed:
    return embed("❌ Erreur", msg, color="error")


def success(msg: str) -> discord.Embed:
    return embed("✅ Succès", msg, color="success")


def warn(msg: str) -> discord.Embed:
    return embed("⚠️ Attention", msg, color="warn")
