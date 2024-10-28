import discord
from discord.ext import commands, tasks
import importlib
import aiosqlite
import atexit
import psutil
from datetime import datetime
import os

# Botのインテントを設定
intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.message_content = True

main = commands.Bot(command_prefix='!', intents=intents)

# SQLiteデータベースの初期化
db_connection = None

async def init_db():
    global db_connection
    db_connection = await aiosqlite.connect('channels.db')
    await db_connection.execute('CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY)')
    await db_connection.commit()

async def close_db():
    if db_connection:
        await db_connection.close()

# チャンネルをデータベースに登録
async def register_channel(channel_id):
    async with db_connection.execute('INSERT OR IGNORE INTO channels (id) VALUES (?)', (channel_id,)):
        await db_connection.commit()

# チャンネルをデータベースから削除
async def unregister_channel(channel_id):
    async with db_connection.execute('DELETE FROM channels WHERE id = ?', (channel_id,)):
        await db_connection.commit()

# チャンネルリストを取得
async def get_registered_channels():
    async with db_connection.execute('SELECT id FROM channels') as cursor:
        return [row[0] for row in await cursor.fetchall()]

# 定期的にBOTの状態を更新するためのタスク
status_channel_id = 1300468412257927189
status_message = None
is_running = True  # BOTが稼働中かどうかのフラグ

@tasks.loop(seconds=30)
async def update_status():
    global status_message, is_running
    channel = main.get_channel(status_channel_id)

    if channel is not None:
        registered_channels = await get_registered_channels()
        current_channel_count = len(registered_channels)

        embed = discord.Embed(
            title='BOTの状態',
            description='正常稼働中' if is_running else '停止中',
            color=0x00FF00 if is_running else 0xFF0000
        )
        embed.add_field(name='接続数', value=current_channel_count, inline=False)
        embed.set_footer(text=f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if status_message is None:
            status_message = await channel.send(embed=embed)
        else:
            await status_message.edit(embed=embed)

@main.event
async def on_ready():
    await init_db()
    await main.tree.sync()

    registered_channels = await get_registered_channels()
    current_channel_count = len(registered_channels)
    
    embed = discord.Embed(
        title='接続完了',
        description=f'ボットが起動しました！登録チャンネル数: {current_channel_count}',
        color=0x00FF00
    )
    
    for channel_id in registered_channels:
        target_channel = main.get_channel(channel_id)
        if target_channel and target_channel.permissions_for(target_channel.guild.me).send_messages:
            await target_channel.send(embed=embed)

    await main.change_presence(activity=discord.Game(name=f"接続数: {current_channel_count}"))
    
    update_status.start()

@main.tree.command(name='yomikomi', description='bot.pyを再読み込みします。')
async def reload_bot(interaction: discord.Interaction):
    await interaction.response.send_message('ボットを再読み込み中です...', ephemeral=True)

    try:
        import main  # メインボットスクリプトをインポート
        importlib.reload(main)  # モジュールをリロード
        await interaction.channel.send('ボットの再読み込みが完了しました。')
    except Exception as e:
        await interaction.channel.send(f'再読み込み中にエラーが発生しました: {e}')


@main.tree.command(name='status', description='サーバーのCPUおよびメモリ使用率を表示します。')
async def server_status(interaction: discord.Interaction):
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    memory_usage = memory.percent

    embed = discord.Embed(title="サーバーの負荷状況", color=0x3498db)
    embed.add_field(name="CPU使用率", value=f"{cpu_usage}%", inline=False)
    embed.add_field(name="メモリ使用率", value=f"{memory_usage}%", inline=False)
    embed.set_footer(text="リアルタイムでのサーバーの負荷を表示しています。")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@main.tree.command(name='list', description='現在の登録チャンネルのリストと接続数を表示します。')
async def list_global_chat_channels(interaction: discord.Interaction):
    registered_channels = await get_registered_channels()
    current_channel_count = len(registered_channels)

    embed = discord.Embed(
        title='登録チャンネルリスト',
        description=f'現在の接続数: {current_channel_count}',
        color=0x00FF00
    )

    if current_channel_count > 0:
        server_info = []
        for channel_id in registered_channels:
            channel = main.get_channel(channel_id)
            if channel and channel.guild:
                server_info.append(f"{channel.guild.name} - メンバー数: {channel.guild.member_count}")

        embed.add_field(name='サーバー一覧', value="\n".join(server_info), inline=False)
    else:
        embed.add_field(name='サーバー', value='登録されているサーバーはありません。', inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@main.tree.command(name='start', description='グローバルチャットを開始します。')
async def start_global_chat(interaction: discord.Interaction):
    channel = interaction.channel
    await register_channel(channel.id)
    await interaction.response.send_message('グローバルチャットを開始しました！', ephemeral=True)

    embed = discord.Embed(
        title='グローバルチャット開始',
        description=f'{interaction.guild.name}でグローバルチャットが開始されました！',
        color=0x9B95C9
    )
    
    for channel_id in await get_registered_channels():
        target_channel = main.get_channel(channel_id)
        if target_channel and target_channel.permissions_for(target_channel.guild.me).send_messages:
            await target_channel.send(embed=embed)

    registered_channels = await get_registered_channels()
    await main.change_presence(activity=discord.Game(name=f"{len(registered_channels)} チャンネルに接続中"))

@main.tree.command(name='stop', description='グローバルチャットを停止します。')
async def stop_global_chat(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    await unregister_channel(channel_id)  # データベースから削除
    await interaction.response.send_message('グローバルチャットを停止しました。', ephemeral=True)

    registered_channels = await get_registered_channels()
    current_channel_count = len(registered_channels)

    embed = discord.Embed(
        title='グローバルチャット停止',
        description=f'{interaction.guild.name} からグローバルチャットが停止されました。',
        color=0xFF0000
    )
    embed.add_field(name='現在の登録チャンネル数', value=f"{current_channel_count}", inline=True)

    # 全サーバーに停止通知を送信
    for channel_id in registered_channels:
        target_channel = main.get_channel(channel_id)
        if target_channel and target_channel.permissions_for(target_channel.guild.me).send_messages:
            await target_channel.send(embed=embed)

@main.event
async def on_message(message):
    if message.author == main.user:
        return

    if isinstance(message.channel, discord.DMChannel):
        return

    registered_channels = await get_registered_channels()
    if message.channel.id in registered_channels:
        embed = discord.Embed(
            description=message.content,
            color=0x9B95C9
        )
        embed.set_author(
            name=f"{message.author.name}#{message.author.discriminator}",
            icon_url=str(message.author.avatar.url) if message.author.avatar else None
        )
        embed.set_footer(
            text=f"{message.guild.name} / mID: {message.id}",
            icon_url=str(message.guild.icon.url) if message.guild.icon else None
        )

        if message.attachments:
            embed.set_image(url=message.attachments[0].url)

        for channel_id in registered_channels:
            target_channel = main.get_channel(channel_id)
            if target_channel and target_channel.guild.id != message.guild.id and target_channel.permissions_for(target_channel.guild.me).send_messages:
                await target_channel.send(embed=embed)

        await message.add_reaction('✅')

# プログラム終了時にデータベースを閉じる
atexit.register(lambda: main.loop.run_until_complete(close_db()))

# Botのトークンをここに入れてください
main.run(os.environ['DISCORD_BOT_TOKEN'])