import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import os
import json

TOKEN = os.getenv("TOKEN")

# 参加者ロールID
PARTICIPANT_ROLE_ID = 123456789012345678

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "threads.json"

DEFAULT_TIME = 60 * 60
WARNING_TIME = 5 * 60


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


threads = load_data()


class RecruitView(discord.ui.View):

    def __init__(self, thread_id):
        super().__init__(timeout=None)
        self.thread_id = str(thread_id)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):

        data = threads.get(self.thread_id)

        if not data:
            return await interaction.response.send_message("募集データがありません", ephemeral=True)

        user = interaction.user

        if user.id in data["members"]:
            return await interaction.response.send_message("すでに参加しています", ephemeral=True)

        if data["max_members"] and len(data["members"]) >= data["max_members"]:
            return await interaction.response.send_message("この募集は満員です", ephemeral=True)
            thread = interaction.channel

everyone = interaction.guild.default_role
role = interaction.guild.get_role(PARTICIPANT_ROLE_ID)

# everyone書き込み禁止
await thread.set_permissions(everyone, send_messages=False)

# 参加者ロール書き込み許可
if role:
    await thread.set_permissions(role, send_messages=True)

await thread.send("🔒 参加者のみ書き込み可能になりました")

        data["members"].append(user.id)
        save_data(threads)

        count = len(data["members"])

        await interaction.channel.send(f"✅ {user.mention} が参加しました")

        if data["max_members"]:
            await interaction.channel.send(f"👥 現在 {count}/{data['max_members']} 人")

        await interaction.response.defer()

        # 満員処理
        if data["max_members"] and count >= data["max_members"]:

            await interaction.channel.send("🎉 **募集が満員になりました！**")

            guild = interaction.guild
            role = guild.get_role(PARTICIPANT_ROLE_ID)

            for uid in data["members"]:
                member = guild.get_member(uid)

                if member and role:
                    try:
                        await member.add_roles(role)
                    except:
                        pass

            await interaction.channel.send("🏷 参加者にロールを付与しました")

            await interaction.channel.send("🔒 募集スレッドをロックします")

            await interaction.channel.edit(locked=True)

    @discord.ui.button(label="落ち", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):

        data = threads.get(self.thread_id)

        if not data:
            return await interaction.response.send_message("募集データがありません", ephemeral=True)

        user = interaction.user

        if user.id not in data["members"]:
            return await interaction.response.send_message("参加していません", ephemeral=True)

        data["members"].remove(user.id)
        save_data(threads)

        await interaction.channel.send(f"❌ {user.mention} が募集から抜けました")

        await interaction.response.defer()


@bot.event
async def on_ready():

    print(f"起動しました: {bot.user}")

    await bot.tree.sync()

    for thread_id in threads.keys():
        bot.add_view(RecruitView(thread_id))

    check_threads.start()


@bot.event
async def on_thread_create(thread):

    threads[str(thread.id)] = {
        "last_activity": time.time(),
        "limit": DEFAULT_TIME,
        "members": [],
        "max_members": None,
        "warned": False
    }

    save_data(threads)

    view = RecruitView(thread.id)

    await thread.send(
        "🎮 **募集開始！**\n\n"
        "参加する人はボタンを押してください！\n"
        "⏰ 60分活動がないと自動終了します。",
        view=view
    )


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if isinstance(message.channel, discord.Thread):

        data = threads.get(str(message.channel.id))

        if data:
            data["last_activity"] = time.time()
            data["warned"] = False
            save_data(threads)

    await bot.process_commands(message)


@tasks.loop(minutes=1)
async def check_threads():

    now = time.time()

    for thread_id in list(threads.keys()):

        thread = bot.get_channel(int(thread_id))

        if not thread:
            threads.pop(thread_id)
            save_data(threads)
            continue

        data = threads[thread_id]

        inactive = now - data["last_activity"]
        remain = data["limit"] - inactive

        if remain <= WARNING_TIME and not data["warned"]:

            try:
                await thread.send("⏰ この募集は **あと5分で締め切られます！**")
                data["warned"] = True
                save_data(threads)
            except:
                pass

        if remain <= 0:

            try:

                member_mentions = []

                for uid in data["members"]:
                    member_mentions.append(f"<@{uid}>")

                members_text = "\n".join(member_mentions) if member_mentions else "参加者なし"

                await thread.send(
                    f"🎮 **募集終了！**\n\n"
                    f"参加者\n{members_text}"
                )

                guild = thread.guild
                role = guild.get_role(PARTICIPANT_ROLE_ID)

                for uid in data["members"]:
                    member = guild.get_member(uid)

                    if member and role:
                        try:
                            await member.remove_roles(role)
                        except:
                            pass

                await thread.send("🏷 参加者ロールを削除しました")

                await thread.edit(archived=True, locked=True)

            except:
                pass

            threads.pop(thread_id)
            save_data(threads)


@bot.tree.command(name="人数", description="募集人数を設定")
async def set_members(interaction: discord.Interaction, number: int):

    if not isinstance(interaction.channel, discord.Thread):
        return await interaction.response.send_message("スレッドで使用してください", ephemeral=True)

    data = threads.get(str(interaction.channel.id))

    if not data:
        return await interaction.response.send_message("募集データがありません", ephemeral=True)

    data["max_members"] = number
    save_data(threads)

    await interaction.response.send_message(
        f"👥 募集人数を **{number}人** に設定しました！"
    )


@bot.tree.command(name="延長", description="募集時間を延長")
async def extend(interaction: discord.Interaction, minutes: int):

    if not isinstance(interaction.channel, discord.Thread):
        return await interaction.response.send_message("スレッドで使ってください", ephemeral=True)

    data = threads.get(str(interaction.channel.id))

    if not data:
        return await interaction.response.send_message("募集データがありません", ephemeral=True)

    data["limit"] += minutes * 60
    save_data(threads)

    await interaction.response.send_message(
        f"⏰ 募集時間を **{minutes}分延長**しました！"
    )


@bot.tree.command(name="残り時間", description="募集の残り時間")
async def remaining(interaction: discord.Interaction):

    if not isinstance(interaction.channel, discord.Thread):
        return await interaction.response.send_message("スレッドで使用してください", ephemeral=True)

    data = threads.get(str(interaction.channel.id))

    if not data:
        return await interaction.response.send_message("募集データがありません", ephemeral=True)

    now = time.time()
    inactive = now - data["last_activity"]
    remain = int((data["limit"] - inactive) / 60)

    await interaction.response.send_message(
        f"⏰ 残り時間 **{remain}分**"
    )


bot.run(TOKEN)