import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import json
import os
import asyncio
import time

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ データベース初期化
def init_db():
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            guild_id INTEGER,
            name TEXT,
            recruit_channel INTEGER,
            forum_channel INTEGER,
            modes TEXT DEFAULT '[]',
            mention_role INTEGER DEFAULT NULL,
            PRIMARY KEY (guild_id, name)
        )
    """)
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
            mode TEXT DEFAULT '',
            guests INTEGER DEFAULT 0,
            guild_id INTEGER DEFAULT NULL,
            end_time REAL DEFAULT NULL
        )
    """)
    for col in ["mode TEXT DEFAULT ''", "guests INTEGER DEFAULT 0",
                "guild_id INTEGER DEFAULT NULL", "end_time REAL DEFAULT NULL"]:
        try:
            c.execute(f"ALTER TABLE recruits ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

# ✅ ゲーム関連DB操作
def db_add_game(guild_id, name, recruit_channel, forum_channel, modes: list, mention_role: int = None):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO games VALUES (?, ?, ?, ?, ?, ?)",
              (guild_id, name, recruit_channel, forum_channel,
               json.dumps(modes, ensure_ascii=False), mention_role))
    conn.commit()
    conn.close()

def db_get_games(guild_id):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM games WHERE guild_id = ?", (guild_id,))
    rows = c.fetchall()
    conn.close()
    return {
        row[1]: {
            "recruit_channel": row[2],
            "forum_channel": row[3],
            "modes": json.loads(row[4]) if row[4] else [],
            "mention_role": row[5]
        }
        for row in rows
    }

def db_get_game(guild_id, name):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM games WHERE guild_id = ? AND name = ?", (guild_id, name))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "recruit_channel": row[2],
            "forum_channel": row[3],
            "modes": json.loads(row[4]) if row[4] else [],
            "mention_role": row[5]
        }
    return None

def db_delete_game(guild_id, name):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("DELETE FROM games WHERE guild_id = ? AND name = ?", (guild_id, name))
    conn.commit()
    conn.close()

# ✅ 募集関連DB操作
def db_save_recruit(message_id, recruit):
    conn = sqlite3.connect("/data/data.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO recruits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        str(message_id),
        recruit["host"],
        recruit["game"],
        recruit["title"],
        recruit["limit"],
        json.dumps(recruit["members"]),
        recruit["comment"],
        recruit.get("thread_id"),
        recruit.get("mode", ""),
        recruit.get("guests", 0),
        recruit.get("guild_id"),
        recruit.get("end_time")
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
            "mode": row[8] if len(row) > 8 else "",
            "guests": row[9] if len(row) > 9 else 0,
            "guild_id": row[10] if len(row) > 10 else None,
            "end_time": row[11] if len(row) > 11 else None
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
    host = recruit["host"]
    guests = recruit.get("guests", 0)
    all_members = [host] + [m for m in members if m != host]
    member_lines = [f"<@{m}> {'👑' if m == host else ''}" for m in all_members]
    member_lines += ["No name 👤"] * guests
    member_text = "\n".join(member_lines) if member_lines else "なし"
    mode = recruit.get("mode", "")
    total = len(members) + 1 + guests
    end_time = recruit.get("end_time")

    embed = discord.Embed(
        title=f"🎮 {recruit['game']}募集",
        description=f"📌 {recruit['title']}",
        color=discord.Color.blue()
    )
    if mode:
        embed.add_field(name="🏷️ モード", value=mode, inline=False)
    embed.add_field(name="👥 人数", value=f"{total} / {recruit['limit']}", inline=False)
    if end_time:
        embed.add_field(name="⏰ 募集終了", value=f"<t:{int(end_time)}:R>", inline=False)
    embed.add_field(name="💬 一言", value=recruit["comment"], inline=False)
    embed.add_field(name="参加者", value=member_text, inline=False)
    return embed


# ✅ オートコンプリート関数
async def game_autocomplete(interaction: discord.Interaction, current: str):
    try:
        games = db_get_games(interaction.guild_id)
        return [
            app_commands.Choice(name=name, value=name)
            for name in games if current.lower() in name.lower()
        ][:25]
    except Exception as e:
        print(f"game_autocomplete エラー: {e}")
        return []

async def mode_autocomplete(interaction: discord.Interaction, current: str):
    game_name = getattr(interaction.namespace, "ゲーム", None)
    if not game_name:
        return []
    game = db_get_game(interaction.guild_id, game_name)
    if not game or not game["modes"]:
        return []
    return [
        app_commands.Choice(name=mode, value=mode)
        for mode in game["modes"] if current.lower() in mode.lower()
    ][:25]


# ✅ スレッド取得ヘルパー
async def get_thread(thread_id):
    if not thread_id:
        return None
    thread = bot.get_channel(thread_id)
    if not thread:
        try:
            thread = await bot.fetch_channel(thread_id)
        except discord.NotFound:
            return None
    return thread


# ✅ 「募集参加者」ロール関連ヘルパー
def get_recruit_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name="募集参加者")

async def add_recruit_role(guild: discord.Guild, user_id: int):
    role = get_recruit_role(guild)
    if not role:
        return
    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if member and role not in member.roles:
        await member.add_roles(role)

async def remove_recruit_role(guild: discord.Guild, user_id: int):
    role = get_recruit_role(guild)
    if not role:
        return
    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if member and role in member.roles:
        await member.remove_roles(role)


# ✅ 募集自動終了処理
async def auto_end_recruit(message_id: str, is_archive: bool = True):
    try:
        recruit = db_get_recruit(message_id)
        if not recruit:
            return

        guild_id = recruit.get("guild_id")
        guild = bot.get_guild(guild_id) if guild_id else None

        if is_archive:
            # スレッドをアーカイブ
            thread = await get_thread(recruit.get("thread_id"))
            if thread:
                try:
                    await thread.send("⏰ 募集時間が終了しました。スレッドをアーカイブします。")
                    await thread.edit(archived=True)
                    print(f"[タイマー] スレッドアーカイブ完了: {message_id}")
                except Exception as e:
                    print(f"[タイマー] スレッドアーカイブ失敗: {e}")
        else:
            # 完全終了
            thread = await get_thread(recruit.get("thread_id"))
            if thread:
                try:
                    await thread.edit(archived=True, locked=True)
                except Exception as e:
                    print(f"[タイマー] スレッドロック失敗: {e}")

            if guild:
                game = db_get_game(guild_id, recruit["game"])
                if game:
                    channel = bot.get_channel(game["recruit_channel"])
                    if channel:
                        try:
                            msg = await channel.fetch_message(int(message_id))
                            await msg.delete()
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            print(f"[タイマー] メッセージ削除失敗: {e}")

                await remove_recruit_role(guild, recruit["host"])
                for member_id in recruit["members"]:
                    await remove_recruit_role(guild, member_id)

            db_delete_recruit(message_id)
            print(f"[タイマー] 募集自動終了完了: {message_id}")

    except Exception as e:
        print(f"[タイマー] 予期しないエラー: {e}")


# ✅ タイマー監視ループ（30秒ごとにDBをチェック）
async def timer_loop():
    await bot.wait_until_ready()
    print("[タイマー] 監視ループ開始")
    # アーカイブ済みフラグをメモリで管理
    archived_ids: set = set()
    while not bot.is_closed():
        try:
            now = time.time()
            for msg_id in db_get_all_recruits():
                recruit = db_get_recruit(msg_id)
                if not recruit:
                    continue
                end_time = recruit.get("end_time")
                if not end_time:
                    continue

                # 募集時間終了 → スレッドアーカイブ
                if now >= end_time and msg_id not in archived_ids:
                    print(f"[タイマー] 募集時間終了検知: {msg_id}")
                    archived_ids.add(msg_id)
                    asyncio.create_task(auto_end_recruit(msg_id, is_archive=True))

                # アーカイブから1時間後 → 完全終了
                if now >= end_time + 3600 and msg_id in archived_ids:
                    print(f"[タイマー] 完全終了検知: {msg_id}")
                    archived_ids.discard(msg_id)
                    asyncio.create_task(auto_end_recruit(msg_id, is_archive=False))

        except Exception as e:
            print(f"[タイマー] ループエラー: {e}")

        await asyncio.sleep(30)  # 30秒ごとにチェック


# ✅ 募集延長の時間選択ビュー
class ExtendView(discord.ui.View):

    def __init__(self, message_id):
        super().__init__(timeout=30)
        self.message_id = str(message_id)

    async def do_extend(self, interaction: discord.Interaction, minutes: int):
        recruit = db_get_recruit(self.message_id)
        if not recruit:
            return await interaction.response.edit_message(content="募集データなし", view=None)

        current_end = recruit.get("end_time") or time.time()
        # すでに終了時間を過ぎている場合は現在時刻から延長
        new_end = max(current_end, time.time()) + minutes * 60
        recruit["end_time"] = new_end
        db_save_recruit(self.message_id, recruit)

        # embedを更新
        game = db_get_game(interaction.guild_id, recruit["game"])
        if game:
            channel = bot.get_channel(game["recruit_channel"])
            if channel:
                try:
                    msg = await channel.fetch_message(int(self.message_id))
                    embed = create_embed(recruit)
                    await msg.edit(embed=embed)
                except discord.NotFound:
                    pass

        await interaction.response.edit_message(
            content=f"✅ 募集を{minutes}分延長しました！\n終了: <t:{int(new_end)}:R>",
            view=None
        )

    @discord.ui.button(label="10分", style=discord.ButtonStyle.blurple)
    async def extend_10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.do_extend(interaction, 10)

    @discord.ui.button(label="30分", style=discord.ButtonStyle.blurple)
    async def extend_30(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.do_extend(interaction, 30)

    @discord.ui.button(label="60分", style=discord.ButtonStyle.blurple)
    async def extend_60(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.do_extend(interaction, 60)


# ✅ 募集終了の確認ビュー
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

        thread = await get_thread(recruit.get("thread_id"))
        if thread:
            await thread.edit(archived=True, locked=True)

        game = db_get_game(interaction.guild_id, recruit["game"])
        if game:
            channel = bot.get_channel(game["recruit_channel"])
            try:
                msg = await channel.fetch_message(int(self.message_id))
                await msg.delete()
            except discord.NotFound:
                pass

        guild = interaction.guild
        await remove_recruit_role(guild, recruit["host"])
        for member_id in recruit["members"]:
            await remove_recruit_role(guild, member_id)

        db_delete_recruit(self.message_id)
        await interaction.response.edit_message(content="✅ 募集を終了しました。", view=None)

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)


# ✅ 募集ビュー（スレッドを閉じるボタン削除）
class RecruitView(discord.ui.View):

    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = str(message_id)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green, custom_id="recruit_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id == recruit["host"]:
            return await interaction.response.send_message("募集主は参加できません", ephemeral=True)
        if interaction.user.id in recruit["members"]:
            return await interaction.response.send_message("すでに参加しています", ephemeral=True)
        if len(recruit["members"]) + 1 + recruit.get("guests", 0) >= recruit["limit"]:
            return await interaction.response.send_message("満員です", ephemeral=True)

        recruit["members"].append(interaction.user.id)
        db_save_recruit(self.message_id, recruit)

        await add_recruit_role(interaction.guild, interaction.user.id)

        thread = await get_thread(recruit.get("thread_id"))
        if thread:
            await thread.send(f"✅ {interaction.user.mention} が参加しました！")

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("参加しました", ephemeral=True)

    @discord.ui.button(label="落ち", style=discord.ButtonStyle.red, custom_id="recruit_leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id == recruit["host"]:
            return await interaction.response.send_message("募集主は使用できません", ephemeral=True)
        if interaction.user.id not in recruit["members"]:
            return await interaction.response.send_message("参加していません", ephemeral=True)

        recruit["members"].remove(interaction.user.id)
        db_save_recruit(self.message_id, recruit)

        await remove_recruit_role(interaction.guild, interaction.user.id)

        thread = await get_thread(recruit.get("thread_id"))
        if thread:
            await thread.send(f"❌ {interaction.user.mention} が抜けました。")

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("募集から抜けました", ephemeral=True)

    @discord.ui.button(label="お友達参加", style=discord.ButtonStyle.green, custom_id="recruit_guest_join")
    async def guest_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)

        guests = recruit.get("guests", 0)
        total = len(recruit["members"]) + 1 + guests
        if total >= recruit["limit"]:
            return await interaction.response.send_message("満員です", ephemeral=True)

        recruit["guests"] = guests + 1
        db_save_recruit(self.message_id, recruit)

        thread = await get_thread(recruit.get("thread_id"))
        if thread:
            await thread.send(f"✅ {interaction.user.mention} がお友達を追加しました！")

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("お友達を追加しました", ephemeral=True)

    @discord.ui.button(label="お友達落ち", style=discord.ButtonStyle.red, custom_id="recruit_guest_leave")
    async def guest_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)

        guests = recruit.get("guests", 0)
        if guests <= 0:
            return await interaction.response.send_message("お友達参加者がいません", ephemeral=True)

        recruit["guests"] = guests - 1
        db_save_recruit(self.message_id, recruit)

        thread = await get_thread(recruit.get("thread_id"))
        if thread:
            await thread.send(f"❌ {interaction.user.mention} がお友達を1名キャンセルしました。")

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("お友達をキャンセルしました", ephemeral=True)

    @discord.ui.button(label="スレッドを再開", style=discord.ButtonStyle.blurple, custom_id="recruit_thread_reopen")
    async def thread_reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        thread = await get_thread(recruit.get("thread_id"))
        if not thread:
            return await interaction.response.send_message("スレッドが見つかりません", ephemeral=True)

        await thread.edit(archived=False)
        await interaction.response.send_message("スレッドを再開しました", ephemeral=True)

    @discord.ui.button(label="募集延長", style=discord.ButtonStyle.blurple, custom_id="recruit_extend")
    async def extend_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        extend_view = ExtendView(self.message_id)
        await interaction.response.send_message(
            "⏰ 何分延長しますか？",
            view=extend_view,
            ephemeral=True
        )

    @discord.ui.button(label="募集終了", style=discord.ButtonStyle.red, custom_id="recruit_end")
    async def end_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = db_get_recruit(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        confirm_view = ConfirmView(self.message_id)
        await interaction.response.send_message(
            "⚠️ 本当に募集を終了しますか？\nスレッドがロックされ、募集メッセージが削除されます。",
            view=confirm_view,
            ephemeral=True
        )


# ✅ グローバルにコマンドを同期・タイマーループ起動
@bot.event
async def on_ready():
    print(f"起動しました {bot.user}")
    await bot.tree.sync()
    print("コマンド同期完了")
    for msg_id in db_get_all_recruits():
        bot.add_view(RecruitView(msg_id))
    # タイマー監視ループを起動
    asyncio.create_task(timer_loop())


# ✅ ゲーム追加
@bot.tree.command(name="ゲーム追加", description="ゲーム設定追加")
async def add_game(interaction: discord.Interaction,
                   ゲーム名: str,
                   募集チャンネル: discord.TextChannel,
                   フォーラムチャンネル: discord.ForumChannel,
                   メンションロール: discord.Role = None,
                   モード1: str = "",
                   モード2: str = "",
                   モード3: str = "",
                   モード4: str = "",
                   モード5: str = ""):
    modes = [m for m in [モード1, モード2, モード3, モード4, モード5] if m.strip()]
    db_add_game(interaction.guild_id, ゲーム名, 募集チャンネル.id, フォーラムチャンネル.id,
                modes, メンションロール.id if メンションロール else None)

    mode_text = "、".join(modes) if modes else "なし"
    role_text = メンションロール.mention if メンションロール else "なし"
    await interaction.response.send_message(
        f"✅ **{ゲーム名}** を登録しました\n🏷️ モード: {mode_text}\n📣 メンションロール: {role_text}"
    )


@bot.tree.command(name="ゲーム一覧", description="登録済みゲーム一覧を表示")
async def game_list(interaction: discord.Interaction):
    games = db_get_games(interaction.guild_id)
    if not games:
        return await interaction.response.send_message("ゲームなし")

    lines = []
    for name, data in games.items():
        modes = "、".join(data["modes"]) if data["modes"] else "なし"
        role_id = data.get("mention_role")
        role_text = f"<@&{role_id}>" if role_id else "なし"
        lines.append(f"**{name}** - モード: {modes} / メンション: {role_text}")

    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="ゲーム削除", description="登録済みゲームを削除")
@app_commands.autocomplete(ゲーム名=game_autocomplete)
async def delete_game(interaction: discord.Interaction, ゲーム名: str):
    game = db_get_game(interaction.guild_id, ゲーム名)
    if not game:
        return await interaction.response.send_message("そのゲームは登録されていません", ephemeral=True)
    db_delete_game(interaction.guild_id, ゲーム名)
    await interaction.response.send_message(f"✅ {ゲーム名} を削除しました", ephemeral=True)


# ✅ 募集（募集時間対応）
@bot.tree.command(name="募集", description="ゲームの募集を作成")
@app_commands.autocomplete(ゲーム=game_autocomplete, モード=mode_autocomplete)
async def recruit(interaction: discord.Interaction,
                  ゲーム: str,
                  募集名: str,
                  遊ぶ人数: int,
                  一言: str,
                  募集時間: int,
                  モード: str = ""):

    game = db_get_game(interaction.guild_id, ゲーム)
    if not game:
        return await interaction.response.send_message("ゲーム未登録", ephemeral=True)
    if 募集時間 <= 0:
        return await interaction.response.send_message("募集時間は1分以上で設定してください", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    channel = bot.get_channel(game["recruit_channel"])
    end_time = time.time() + 募集時間 * 60  # 分 → 秒に変換

    recruit_data = {
        "host": interaction.user.id,
        "game": ゲーム,
        "title": 募集名,
        "limit": 遊ぶ人数,
        "members": [],
        "comment": 一言,
        "thread_id": None,
        "mode": モード,
        "guests": 0,
        "guild_id": interaction.guild_id,
        "end_time": end_time
    }

    embed = create_embed(recruit_data)
    mention_role_id = game.get("mention_role")
    mention_text = f"<@&{mention_role_id}>" if mention_role_id else None
    msg = await channel.send(content=mention_text, embed=embed)

    forum = bot.get_channel(game["forum_channel"])
    thread = await forum.create_thread(
        name=募集名,
        content=f"🎮 **{募集名}** のスレッドです！\n主催: {interaction.user.mention}\n⏰ 募集時間: {募集時間}分",
        auto_archive_duration=60
    )

    recruit_data["thread_id"] = thread.thread.id
    db_save_recruit(str(msg.id), recruit_data)

    await add_recruit_role(interaction.guild, interaction.user.id)

    view = RecruitView(msg.id)
    await msg.edit(view=view)

    await interaction.followup.send(f"✅ 募集を作成しました（募集時間: {募集時間}分）", ephemeral=True)


bot.run(TOKEN)
