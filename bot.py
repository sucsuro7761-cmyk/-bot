import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import json
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ データベース初期化
def init_db():
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            name TEXT PRIMARY KEY,
            recruit_channel INTEGER,
            forum_channel INTEGER,
            modes TEXT DEFAULT '[]'
        )
    """)
    # 既存テーブルにmodesカラムがない場合は追加
    try:
        c.execute("ALTER TABLE games ADD COLUMN modes TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass  # すでに存在する場合は無視

    c.execute("""
        CREATE TABLE IF NOT EXISTS recruits (
            message_id TEXT PRIMARY KEY,
            host INTEGER,
            game TEXT,
            title TEXT,
            limit_ INTEGER,
            members TEXT,
            comment TEXT,
            thread_id INTEGER,
            mode TEXT DEFAULT ''
        )
    """)
    # 既存テーブルにmodeカラムがない場合は追加
    try:
        c.execute("ALTER TABLE recruits ADD COLUMN mode TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

# ✅ ゲーム関連DB操作
def db_add_game(name, recruit_channel, forum_channel, modes: list):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO games VALUES (?, ?, ?, ?)",
              (name, recruit_channel, forum_channel, json.dumps(modes, ensure_ascii=False)))
    conn.commit()
    conn.close()

def db_get_games():
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM games")
    rows = c.fetchall()
    conn.close()
    return {
        row[0]: {
            "recruit_channel": row[1],
            "forum_channel": row[2],
            "modes": json.loads(row[3]) if row[3] else []
        }
        for row in rows
    }

def db_get_game(name):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM games WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "recruit_channel": row[1],
            "forum_channel": row[2],
            "modes": json.loads(row[3]) if row[3] else []
        }
    return None

def db_delete_game(name):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("DELETE FROM games WHERE name = ?", (name,))
    conn.commit()
    conn.close()

# ✅ 募集関連DB操作
def db_save_recruit(message_id, recruit):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO recruits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        str(message_id),
        recruit["host"],
        recruit["game"],
        recruit["title"],
        recruit["limit"],
        json.dumps(recruit["members"]),
        recruit["comment"],
        recruit.get("thread_id"),
        recruit.get("mode", "")
    ))
    conn.commit()
    conn.close()

def db_get_recruit(message_id):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM recruits WHERE message_id = ?", (str(message_id),))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "host": row[1],
            "game": row[2],
            "title": row[3],
            "limit": row[4],
            "members": json.loads(row[5]),
            "comment": row[6],
            "thread_id": row[7],
            "mode": row[8] if len(row) > 8 else ""
        }
    return None

def db_get_all_recruits():
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT message_id FROM recruits")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def db_delete_recruit(message_id):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("DELETE FROM recruits WHERE message_id = ?", (str(message_id),))
    conn.commit()
    conn.close()

init_db()

def create_embed(recruit):
    members = recruit["members"]
    member_text = "\n".join([f"<@{m}>" for m in members]) if members else "なし"
    mode = recruit.get("mode", "")

    embed = discord.Embed(
        title=f"🎮 {recruit['game']}募集",
        description=f"📌 {recruit['title']}",
        color=discord.Color.blue()
    )
    if mode:
        embed.add_field(name="🏷️ モード", value=mode, inline=False)
    embed.add_field(name="👥 募集人数", value=f"{len(members)} / {recruit['limit']}", inline=False)
    embed.add_field(name="💬 一言", value=recruit["comment"], inline=False)
    embed.add_field(name="参加者", value=member_text, inline=False)
    return embed


# ✅ オートコンプリート関数
async def game_autocomplete(interaction: discord.Interaction, current: str):
    games = db_get_games()
    return [
        app_commands.Choice(name=name, value=name)
        for name in games if current.lower() in name.lower()
    ][:25]

async def mode_autocomplete(interaction: discord.Interaction, current: str):
    # interaction.namespace で他のオプションの現在値を取得
    game_name = interaction.namespace.ゲーム
    if not game_name:
        return []
    game = db_get_game(game_name)
    if not game or not game["modes"]:
        return []
    return [
        app_commands.Choice(name=mode, value=mode)
        for mode in game["modes"] if current.lower() in mode.lower()
    ][:25]


# ✅ 募集終了の確認ビュー（変更なし）
class ConfirmView(discord.ui.View):

    def __init__(self, message_id):
        super().__init__(timeout=30)
        self.message_id = str(message_id)

    @discord.ui.button(label="✅ はい、終了する", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)
        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        thread_id = recruit.get("thread_id")
        if thread_id:
            thread = bot.get_channel(thread_id)
            if not thread:
                try:
                    thread = await bot.fetch_channel(thread_id)
                except discord.NotFound:
                    pass
            if thread:
                await thread.edit(archived=True, locked=True)

        game = db_get_game(recruit["game"])
        if game:
            channel = bot.get_channel(game["recruit_channel"])
            try:
                msg = await channel.fetch_message(int(self.message_id))
                await msg.delete()
            except discord.NotFound:
                pass

        db_delete_recruit(self.message_id)
        await interaction.response.edit_message(content="✅ 募集を終了しました。", view=None)

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)


class RecruitView(discord.ui.View):

    def __init__(self, message_id):          
        super().__init__(timeout=None)
        self.message_id = str(message_id)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, ...):
        ...


@bot.event
async def on_ready():
    print(f"起動しました {bot.user}")
    await bot.tree.sync()
    for msg_id in db_get_all_recruits():
        bot.add_view(RecruitView(msg_id))


# ✅ ゲーム追加（モード追加対応）
@bot.tree.command(name="ゲーム追加", description="ゲーム設定追加")
async def add_game(interaction: discord.Interaction,
                   ゲーム名: str,
                   募集チャンネル: discord.TextChannel,
                   フォーラムチャンネル: discord.ForumChannel,
                   モード: str = ""):
    """
    モードはカンマ区切りで入力
    例: ランク,カジュアル,カスタム
    """
    modes = [m.strip() for m in モード.split(",") if m.strip()] if モード else []
    db_add_game(ゲーム名, 募集チャンネル.id, フォーラムチャンネル.id, modes)

    mode_text = "、".join(modes) if modes else "なし"
    await interaction.response.send_message(
        f"✅ **{ゲーム名}** を登録しました\n🏷️ モード: {mode_text}"
    )


@bot.tree.command(name="ゲーム一覧", description="登録済みゲーム一覧を表示")
async def game_list(interaction: discord.Interaction):
    games = db_get_games()
    if not games:
        return await interaction.response.send_message("ゲームなし")

    lines = []
    for name, data in games.items():
        modes = "、".join(data["modes"]) if data["modes"] else "なし"
        lines.append(f"**{name}** - モード: {modes}")

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="ゲーム削除", description="登録済みゲームを削除")
@app_commands.autocomplete(ゲーム名=game_autocomplete)
async def delete_game(interaction: discord.Interaction, ゲーム名: str):
    game = db_get_game(ゲーム名)
    if not game:
        return await interaction.response.send_message("そのゲームは登録されていません", ephemeral=True)
    db_delete_game(ゲーム名)
    await interaction.response.send_message(f"✅ {ゲーム名} を削除しました", ephemeral=True)


# ✅ 募集（ゲームオートコンプリート＋モード選択対応）
@bot.tree.command(name="募集", description="ゲームの募集を作成")
@app_commands.autocomplete(ゲーム=game_autocomplete, モード=mode_autocomplete)
async def recruit(interaction: discord.Interaction,
                  ゲーム: str,
                  募集名: str,
                  人数: int,
                  一言: str,
                  モード: str = ""):

    game = db_get_game(ゲーム)
    if not game:
        return await interaction.response.send_message("ゲーム未登録", ephemeral=True)

    channel = bot.get_channel(game["recruit_channel"])

    recruit_data = {
        "host": interaction.user.id,
        "game": ゲーム,
        "title": 募集名,
        "limit": 人数,
        "members": [],
        "comment": 一言,
        "thread_id": None,
        "mode": モード
    }

    embed = create_embed(recruit_data)
    msg = await channel.send(embed=embed)
    view = RecruitView(msg.id)
    await msg.edit(view=view)

    db_save_recruit(str(msg.id), recruit_data)
    await interaction.response.send_message("募集を作成しました", ephemeral=True)


bot.run(TOKEN)
