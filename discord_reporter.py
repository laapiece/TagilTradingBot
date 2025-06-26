# discord_reporter.py
"""
Gère toutes les communications avec l'API Discord.
Envoie les rapports de performance et écoute les commandes utilisateur.
"""

import os
import discord
from discord.ext import commands
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

@bot.event
async def on_ready():
    print(f"{bot.user.name} s'est connecté à Discord!")
    print(f"Prêt à envoyer des rapports dans le canal ID: {DISCORD_CHANNEL_ID}")

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

@bot.command(name='status')
async def status(ctx):
    if not trading_bot_instance:
        await ctx.send("L'instance du bot de trading n'est pas liée.")
        return

    state = trading_bot_instance.get_state()
    color = discord.Color.green() if state['is_running'] and not state['is_paused'] else discord.Color.orange()
    
    status_msg = "Actif"
    if not state['is_running']:
        status_msg = "Arrêté"
        color = discord.Color.red()
    elif state['is_paused']:
        status_msg = f"En pause jusqu'à {state['paused_until'].strftime('%H:%M:%S')}"

    embed = discord.Embed(title="État du Bot de Trading", color=color)
    embed.add_field(name="Statut", value=status_msg, inline=False)
    embed.add_field(name="Solde Initial Journalier", value=f"${state['daily_initial_balance']:.2f}", inline=True)
    embed.add_field(name="Solde Actuel", value=f"${state['current_balance']:.2f}", inline=True)
    embed.add_field(name="Positions Ouvertes", value=str(len(state['open_positions'])), inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='pause')
async def pause(ctx, minutes: int = 60):
    if trading_bot_instance:
        trading_bot_instance.pause(minutes)
        await ctx.send(f"Le bot a été mis en pause pour {minutes} minutes.")
    else:
        await ctx.send("L'instance du bot de trading n'est pas liée.")

@bot.command(name='resume')
async def resume(ctx):
    if trading_bot_instance:
        trading_bot_instance.resume()
        await ctx.send("Le bot a repris ses opérations.")
    else:
        await ctx.send("L'instance du bot de trading n'est pas liée.")

@bot.command(name='backtest')
async def backtest(ctx, start_date: str):
    await ctx.send(f"La fonctionnalité de backtest n'est pas encore implémentée.")

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

if __name__ == '__main__':
    print("Lancement du bot Discord en mode standalone pour test...")
    start_discord_bot(None)
