import os
import discord
from discord.ext import commands
from discord import app_commands # Import app_commands
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Charger les variables d'environnement
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))

# --- Configuration du Bot Discord ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

trading_bot_instance = None

def start_discord_bot(trading_bot_ref):
    global trading_bot_instance
    trading_bot_instance = trading_bot_ref

    if not DISCORD_BOT_TOKEN:
        print("Erreur : Le token du bot Discord n'est pas défini. Le reporter est désactivé.")
        return

    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"Erreur lors du démarrage du bot Discord : {e}")

@bot.event
async def on_ready():
    print(f"{bot.user.name} s'est connecté à Discord!")
    print(f"Prêt à envoyer des rapports dans le canal ID: {DISCORD_CHANNEL_ID}")
    try:
        synced = await bot.tree.sync()
        print(f"Synchronisation des commandes slash réussie. {len(synced)} commandes synchronisées.")
    except Exception as e:
        print(f"Échec de la synchronisation des commandes slash : {e}")

async def send_report(report_data: dict):
    if not DISCORD_CHANNEL_ID or not bot.is_ready():
        print("Avertissement : Le bot Discord n'est pas prêt ou le canal n'est pas configuré.")
        return

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        print(f"Erreur : Impossible de trouver le canal avec l'ID {DISCORD_CHANNEL_ID}")
        return

    embed = discord.Embed(
        title=report_data.get("title", "Rapport de Trading"),
        description=report_data.get("message", ""),
        color=report_data.get("color", discord.Color.blue())
    )

    if "fields" in report_data:
        for field in report_data["fields"]:
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
    
    embed.set_footer(text=f"Bot de Trading IA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    await channel.send(embed=embed)

# --- Commandes Utilisateur ---

@bot.tree.command(name='status', description="Affiche l'état actuel du bot, les trades en cours et les trades récents.")
async def status(interaction: discord.Interaction):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return

    state = trading_bot_instance.get_state()
    color = discord.Color.green() if state['is_running'] and not state['is_paused'] else discord.Color.orange()
    
    status_msg = "Actif"
    if not state['is_running']:
        status_msg = "Arrêté"
        color = discord.Color.red()
    elif state['is_paused']:
        paused_until_str = state['paused_until'].strftime('%Y-%m-%d %H:%M:%S') if state['paused_until'] else "N/A"
        status_msg = f"En pause jusqu'à {paused_until_str}"

    embed = discord.Embed(title="État du Bot de Trading", color=color)
    embed.add_field(name="Statut", value=status_msg, inline=False)
    embed.add_field(name="Symbole de Trading Actuel", value=state['current_trading_symbol'], inline=True)
    embed.add_field(name="Montant de Trade", value=f"${state['trade_amount_usd']:.2f}", inline=True)
    embed.add_field(name="Alertes de Trade Discord", value="Activées" if state['send_trade_alerts'] else "Désactivées", inline=True)
    embed.add_field(name="Solde Initial Journalier", value=f"${state['daily_initial_balance']:.2f}", inline=True)
    embed.add_field(name="Solde Actuel", value=f"${state['current_balance']:.2f}", inline=True)
    
    # Trades en cours
    if state['open_positions']:
        open_positions_str = "\n".join([
            f"- {p['symbol']} ({p['side'].upper()}) @ ${p['price']:.2f} (SL: ${p['stop_loss']:.2f}, TP: ${p['take_profit']:.2f})"
            for p in state['open_positions']
        ])
        embed.add_field(name="Trades en Cours", value=open_positions_str, inline=False)
    else:
        embed.add_field(name="Trades en Cours", value="Aucun", inline=False)

    # Journal des trades des dernières 24h
    recent_trades = trading_bot_instance.get_recent_trades(hours=24)
    if recent_trades:
        recent_trades_str = "\n".join([
            f"- {t['symbol']} ({t['side'].upper()}) @ ${t['price']:.2f} -> P&L: ${t['profit']:.2f} ({t['status']})"
            for t in recent_trades
        ])
        embed.add_field(name="Trades des Dernières 24h", value=recent_trades_str, inline=False)
    else:
        embed.add_field(name="Trades des Dernières 24h", value="Aucun trade récent.", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='pause', description="Met le bot en pause pour une durée spécifiée en minutes.")
async def pause(interaction: discord.Interaction, minutes: int = 60):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    trading_bot_instance.pause(minutes)
    await interaction.response.send_message(f"Le bot a été mis en pause pour {minutes} minutes.")

@bot.tree.command(name='resume', description="Reprend les opérations du bot.")
async def resume(interaction: discord.Interaction):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    trading_bot_instance.resume()
    await interaction.response.send_message("Le bot a repris ses opérations.")

@bot.tree.command(name='toggle_trade_alerts', description="Active ou désactive l'envoi de messages Discord à chaque trade.")
async def toggle_trade_alerts(interaction: discord.Interaction):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    current_state = trading_bot_instance.get_state()['send_trade_alerts']
    trading_bot_instance.set_trade_alerts(not current_state)
    new_state = trading_bot_instance.get_state()['send_trade_alerts']
    await interaction.response.send_message(f"Alertes de trade Discord: {'Activées' if new_state else 'Désactivées'}")

@bot.tree.command(name='manual_order', description="Place un ordre de marché manuellement.")
@app_commands.describe(symbol="Le symbole de l'actif (ex: SPY, AAPL)", side="Le côté de l'ordre (buy/sell)", amount_usd="Le montant en USD à trader")
async def manual_order(interaction: discord.Interaction, symbol: str, side: str, amount_usd: float):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    if side.lower() not in ['buy', 'sell']:
        await interaction.response.send_message("Le côté de l'ordre doit être 'buy' ou 'sell'.")
        return
    
    if amount_usd <= 0:
        await interaction.response.send_message("Le montant doit être supérieur à zéro.")
        return

    await interaction.response.send_message(f"Tentative de placement d'un ordre manuel: {side.upper()} {amount_usd}$ sur {symbol}...")
    success = await trading_bot_instance.manual_execute_trade(symbol.upper(), side.lower(), amount_usd)
    if success:
        # Message de succès envoyé par manual_execute_trade
        pass
    else:
        # Message d'erreur envoyé par manual_execute_trade
        pass

@bot.tree.command(name='set_trade_amount', description="Définit le montant en USD à trader par position.")
@app_commands.describe(amount_usd="Le nouveau montant en USD")
async def set_trade_amount(interaction: discord.Interaction, amount_usd: float):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    if amount_usd <= 0:
        await interaction.response.send_message("Le montant doit être supérieur à zéro.")
        return

    trading_bot_instance.set_trade_amount(amount_usd)
    await interaction.response.send_message(f"Montant de trade défini à **${amount_usd:.2f}**.")

@bot.tree.command(name='set_symbol', description="Définit le symbole de trading principal du bot.")
@app_commands.describe(symbol="Le nouveau symbole (ex: SPY, AAPL)")
async def set_symbol(interaction: discord.Interaction, symbol: str):
    if not trading_bot_instance:
        await interaction.response.send_message("L'instance du bot de trading n'est pas liée.")
        return
    
    trading_bot_instance.set_trading_symbol(symbol.upper())
    await interaction.response.send_message(f"Symbole de trading principal défini à **{symbol.upper()}**.")

@bot.tree.command(name='help_bot', description="Affiche la liste des commandes disponibles.")
async def help_bot(interaction: discord.Interaction):
    embed = discord.Embed(title="Commandes du Bot de Trading", description="Liste des commandes disponibles pour interagir avec le bot.", color=discord.Color.blue())
    embed.add_field(name="/status", value="Affiche l'état actuel du bot, les trades en cours et les trades récents.", inline=False)
    embed.add_field(name="/pause [minutes]", value="Met le bot en pause pour une durée spécifiée (par défaut 60 min).", inline=False)
    embed.add_field(name="/resume", value="Reprend les opérations du bot s'il était en pause.", inline=False)
    embed.add_field(name="/toggle_trade_alerts", value="Active ou désactive l'envoi de messages Discord à chaque trade.", inline=False)
    embed.add_field(name="/manual_order <symbole> <buy/sell> <montant_usd>", value="Place un ordre de marché manuellement pour le symbole et le montant spécifiés.", inline=False)
    embed.add_field(name="/set_trade_amount <montant_usd>", value="Définit le montant en USD à trader par position.", inline=False)
    embed.add_field(name="/set_symbol <symbole>", value="Définit le symbole de trading principal du bot (ex: SPY, AAPL).", inline=False)
    embed.add_field(name="/backtest [date]", value="(Non implémenté) Lance un backtest à partir d'une date spécifiée.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='backtest', description="Lance un backtest (non implémenté).")
@app_commands.describe(start_date="La date de début du backtest (YYYY-MM-DD)")
async def backtest(interaction: discord.Interaction, start_date: str):
    await interaction.response.send_message(f"La fonctionnalité de backtest n'est pas encore implémentée.")

# Commande de synchronisation (commande de préfixe pour être toujours accessible)
@bot.command(name='sync')
async def sync(ctx):
    if ctx.author.id == bot.owner_id: # Optionnel: Limiter à l'owner du bot
        await ctx.send("Synchronisation des commandes slash...")
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"Commandes slash synchronisées : {len(synced)}.")
        except Exception as e:
            await ctx.send(f"Échec de la synchronisation : {e}")
    else:
        await ctx.send("Vous n'êtes pas autorisé à utiliser cette commande.")