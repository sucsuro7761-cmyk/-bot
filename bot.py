import discord
from discord.ext import commands
from discord import app_commands
import json
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"games": {}, "recruits": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

def create_embed(recruit):
    members = recruit["members"]

    if members:
        member_text = "\n".join([f"<@{m}>" for m in members])
    else:
        member_text = "なし"

    embed = discord.Embed(
        title=f"🎮 {recruit['game']}募集",
        description=f"📌 {recruit['title']}",
        color=discord.Color.blue()
    )
    embed.add_field(name="👥 人数", value=f"{len(members)} / {recruit['limit']}", inline=False)
    embed.add_field(name="💬 一言", value=recruit["comment"], inline=False)
    embed.add_field(name="参加者", value=member_text, inline=False)

    return embed


# ✅ 募集終了の確認ビュー
class ConfirmView(discord.ui.View):

    def __init__(self, message_id):
        super().__init__(timeout=30)  # 30秒で確認タイムアウト
        self.message_id = str(message_id)

    @discord.ui.button(label="✅ はい、終了する", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)

        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        # スレッドをロック＆アーカイブ
        thread_id = recruit.get("thread_id")
        if thread_id:
            thread = bot.get_channel(thread_id)
            if thread:
                await thread.edit(archived=True, locked=True)

        # 募集メッセージを削除
        recruit_channel_id = data["games"][recruit["game"]]["recruit_channel"]
        channel = bot.get_channel(recruit_channel_id)
        try:
            msg = await channel.fetch_message(int(self.message_id))
            await msg.delete()
        except discord.NotFound:
            pass

        # データから削除
        del data["recruits"][self.message_id]
        save_data(data)

        await interaction.response.edit_message(content="✅ 募集を終了しました。", view=None)

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="キャンセルしました。", view=None)

    # タイムアウト時の処理
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class RecruitView(discord.ui.View):

    def __init__(self, message_id):
        super().__init__(timeout=None)
        self.message_id = str(message_id)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id in recruit["members"]:
            return await interaction.response.send_message("すでに参加しています", ephemeral=True)
        if len(recruit["members"]) >= recruit["limit"]:
            return await interaction.response.send_message("満員です", ephemeral=True)

        recruit["members"].append(interaction.user.id)
        save_data(data)

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("参加しました", ephemeral=True)

    @discord.ui.button(label="落ち", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id not in recruit["members"]:
            return await interaction.response.send_message("参加していません", ephemeral=True)

        recruit["members"].remove(interaction.user.id)
        save_data(data)

        embed = create_embed(recruit)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("募集から抜けました", ephemeral=True)

    @discord.ui.button(label="スレッド作成", style=discord.ButtonStyle.blurple)
    async def thread_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        # ✅ すでにスレッドが存在する場合は作成しない
        if recruit.get("thread_id"):
            return await interaction.response.send_message("すでにスレッドが作成されています", ephemeral=True)

        game = recruit["game"]
        forum_id = data["games"][game]["forum_channel"]
        forum = bot.get_channel(forum_id)

        thread = await forum.create_thread(
            name=recruit["title"],
            content=f"🎮 {recruit['title']} スレッド",
            auto_archive_duration=60
        )

        # ✅ thread_id を保存
        recruit["thread_id"] = thread.thread.id
        save_data(data)

        await interaction.response.send_message("スレッド作成しました", ephemeral=True)

    # ✅ スレッドを閉じるボタン（アーカイブ）
    @discord.ui.button(label="スレッドを閉じる", style=discord.ButtonStyle.grey)
    async def thread_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        thread_id = recruit.get("thread_id")
        if not thread_id:
            return await interaction.response.send_message("スレッドがまだ作成されていません", ephemeral=True)

        thread = bot.get_channel(thread_id)
        if not thread:
            return await interaction.response.send_message("スレッドが見つかりません", ephemeral=True)

        await thread.edit(archived=True)
        await interaction.response.send_message("スレッドをアーカイブしました", ephemeral=True)

    # ✅ スレッドを再開するボタン（アーカイブ解除）
    @discord.ui.button(label="スレッドを再開", style=discord.ButtonStyle.blurple)
    async def thread_reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

        if not recruit:
            return await interaction.response.send_message("募集データなし", ephemeral=True)
        if interaction.user.id != recruit["host"]:
            return await interaction.response.send_message("募集主のみ使用可能", ephemeral=True)

        thread_id = recruit.get("thread_id")
        if not thread_id:
            return await interaction.response.send_message("スレッドがまだ作成されていません", ephemeral=True)

        thread = bot.get_channel(thread_id)

        # アーカイブ済みのスレッドはget_channelで取れないのでfetchする
        if not thread:
            try:
                thread = await bot.fetch_channel(thread_id)
            except discord.NotFound:
                return await interaction.response.send_message("スレッドが見つかりません", ephemeral=True)

        await thread.edit(archived=False)
        await interaction.response.send_message("スレッドを再開しました", ephemeral=True)

    # ✅ 募集終了ボタン（確認メッセージ付き）
    @discord.ui.button(label="募集終了", style=discord.ButtonStyle.red)
    async def end_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        recruit = data["recruits"].get(self.message_id)

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


@bot.event
async def on_ready():
    print(f"起動しました {bot.user}")
    await bot.tree.sync()
    for msg_id in data["recruits"]:
        bot.add_view(RecruitView(msg_id))


@bot.tree.command(name="ゲーム追加", description="ゲーム設定追加")
async def add_game(interaction: discord.Interaction,
                   ゲーム名: str,
                   募集チャンネル: discord.TextChannel,
                   フォーラムチャンネル: discord.ForumChannel):

    data["games"][ゲーム名] = {
        "recruit_channel": 募集チャンネル.id,
        "forum_channel": フォーラムチャンネル.id
    }
    save_data(data)
    await interaction.response.send_message(f"{ゲーム名} を登録しました")


@bot.tree.command(name="ゲーム一覧")
async def game_list(interaction: discord.Interaction):
    if not data["games"]:
        return await interaction.response.send_message("ゲームなし")
    text = "\n".join(data["games"].keys())
    await interaction.response.send_message(text)


@bot.tree.command(name="募集")
async def recruit(interaction: discord.Interaction,
                  ゲーム: str,
                  募集名: str,
                  人数: int,
                  一言: str):

    if ゲーム not in data["games"]:
        return await interaction.response.send_message("ゲーム未登録")

    recruit_channel_id = data["games"][ゲーム]["recruit_channel"]
    channel = bot.get_channel(recruit_channel_id)

    recruit_data = {
        "host": interaction.user.id,
        "game": ゲーム,
        "title": 募集名,
        "limit": 人数,
        "members": [],
        "comment": 一言,
        "thread_id": None  # ✅ 初期値はNone
    }

    embed = create_embed(recruit_data)
    msg = await channel.send(embed=embed)
    view = RecruitView(msg.id)
    await msg.edit(view=view)

    data["recruits"][str(msg.id)] = recruit_data
    save_data(data)

    await interaction.response.send_message("募集を作成しました", ephemeral=True)


bot.run(TOKEN)