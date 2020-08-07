import asyncio
from datetime import datetime
import requests
import youtube_dl
import discord
from discord.ext import commands
from discord.utils import get
import shutil
import mysql.connector

joined, messages, guildId, songIterator, skipToTime, songStartTime, pauseTime = 0, 0, 0, 0, 0, 0, 0
commandPrefix = "."
loop = False
songQueue, musicTitles, message = {}, {}, {}

embedColor = discord.Color.purple()

token = open("token.txt", "r").read()
ffmpegPathUrl = open("ffmpegPathUrl.txt", "r").read()
creds = open("dbCreds.txt", "r").read().split(";")

# todo add bitrate to ydlOptions (done)
# todo bot leaves from different servers, fix voice.disconnect and voice = get(bot.voice_clients, guild) (done)
# todo launch on_message with asyncio coroutine that can notify functions when event(command invoked)
# todo Track command messages with on_message to remove rubbish
# todo add spotify player [???]
# todo add volume command (done)
# todo loop (done) -> need to avoid global boolean variable loop
# todo extract direct url to youtube from [query] and link it with music title
# todo list a youtube playlist with choice indices on play command
# todo fix url with youtube playlists (currently playing 1st song in playlist, need to play exact one)
# todo create channel [???]
# todo set delete time for play command in settings
# todo add to settings deleting[delete_after] all other commands which are unnecessary
# todo set pause timer in settings

bot = commands.Bot(command_prefix=commands.when_mentioned_or(commandPrefix))
bot.remove_command("help")
musicPath = "data/audio/cache/"
playlistPath = "data/audio/playlist/"

ydlOptions = {
    "format": "bestaudio",
    "noplaylist": True,
    "bitrate": 192000,
    # "quite": True,
    "encoding": "utf-8",
    "default_search": "auto",
    "ignoreerrors": False,
    "no-check-certificate": True,
    "socket_timeout": 30,
    "source_address": "0.0.0.0",
    "extractaudio": True,
    # "audioformat": "mp3",
    "extract_flat": False,
    "simulate": True,
    "prefer_ffmpeg": True,
    "ffmpeg_location": ffmpegPathUrl
}

ffmpegOptions = {
    "before_options": f"-ss {skipToTime} -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}

# todo redo with using a database || reading previous messages (preferred to read)
# async def update_stats():
#     await bot.wait_until_ready()
#     global messages, joined
#     while not bot.is_closed():
#         try:
#             with open("stats.txt", "a") as file:
#                 timestr = datetime.datetime.now()
#                 file.write("Time: {}; Messages: {}; Members joined: {}\n".format(timestr, messages, joined))
#                 messages, joined = 0, 0
#                 await asyncio.sleep(5)
#         except Exception as e:
#             print(e)
#             await asyncio.sleep(5)


@bot.command(pass_context=True)
async def join(ctx):
    await ctx.channel.purge(limit=1)
    channel = ctx.message.author.voice.channel
    voice = get(bot.voice_clients, guild=ctx.guild)

    if voice and voice.is_connected():
        await voice.move_to(channel)
    else:
        voice = await channel.connect()

    await ctx.send("Joined {}".format(channel), delete_after=5)


@bot.command(pass_context=True, aliases=["LEAVE", "disconnect", "DISCONNECT"])
async def leave(ctx):
    global loop, skipToTime
    await ctx.channel.purge(limit=1)
    channel = ctx.message.author.voice.channel
    voice = get(bot.voice_clients, guild=ctx.guild)
    songQueue[ctx.guild], musicTitles[ctx.guild] = [], []

    if voice and voice.is_connected():
        skipToTime = 0
        asyncio.run_coroutine_threadsafe(voice.disconnect(), bot.loop)
        asyncio.run_coroutine_threadsafe(message[ctx.guild].delete(), bot.loop)
        loop = False
        await ctx.send("Left {}".format(channel), delete_after=5)


def parseDuration(duration: int):
    m, s = divmod(duration, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# Queue or queued
async def edit_message(ctx):
    embed = songQueue[ctx.guild][0]["embed"]
    content = "\n".join([f"**{songQueue[ctx.guild].index(i)}:**"
                         f"[{i['title']}]({i['webpage_url']})\n**Requested by:** {ctx.author.mention} "
                         f"**Duration:** {i['duration']}"
                         for i in songQueue[ctx.guild][1:]]) if len(songQueue[ctx.guild]) > 1 else "No songs are queued"

    embed.set_field_at(index=3, name="Queue", value=content, inline=False)
    await message[ctx.guild].edit(embed=embed)


def search(author, url):
    with youtube_dl.YoutubeDL(ydlOptions) as ydl:
        try:
            requests.get(url)
        except:
            info = ydl.extract_info(f"ytsearch:{url}", download=False)["entries"][0]
        else:
            info = ydl.extract_info(url, download=False)

        embed = (discord.Embed(title="Currently playing", description=f"[{info['title']}]({info['webpage_url']})",
                               color=embedColor)
                 .add_field(name="Duration", value=parseDuration(info["duration"]))
                 .add_field(name="Requested by", value=author)
                 .add_field(name="Uploader", value=f"[{info['uploader']}]({info['channel_url']})")
                 .add_field(name="Queue", value="No song queued")
                 .set_thumbnail(url=info["thumbnail"]))

        return {"embed": embed, "source": info["formats"][0]["url"], "title": info["title"],
                "webpage_url": info['webpage_url'], "thumbnail": info["thumbnail"],
                "duration": parseDuration(info["duration"])}


def playNext(ctx):
    global skipToTime, songStartTime, loop
    endTime = songStartTime - datetime.now()
    end = skipToTime
    ffmpegOptions["before_options"] = f"-ss {skipToTime} -reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 " \
                                      f"-reconnect_delay_max 5"
    voice = get(bot.voice_clients, guild=ctx.guild)
    voice.is_paused()

    if loop is True:
        songQueue[ctx.guild].append(songQueue[ctx.guild][0])
        musicTitles[ctx.guild].append(musicTitles[ctx.guild][0])
    else:
        pass

    end += abs(int(endTime.total_seconds()))

    if len(songQueue[ctx.guild]) > 1 and len(musicTitles[ctx.guild]) > 1:
        del songQueue[ctx.guild][0], musicTitles[ctx.guild][0]
        if timeParse(songQueue[ctx.guild][0]["duration"]) <= end:
            skipToTime = 0
            voice.stop()

        song = search(ctx.author.mention, musicTitles[ctx.guild][0])
        songQueue[ctx.guild][0] = song
        asyncio.run_coroutine_threadsafe(edit_message(ctx), bot.loop)
        songStartTime = datetime.now()

        voice.play(discord.FFmpegPCMAudio(executable=ffmpegPathUrl, source=songQueue[ctx.guild][0]["source"],
                                          **ffmpegOptions), after=lambda e: playNext(ctx))
        voice.is_playing()
    else:
        asyncio.run_coroutine_threadsafe(voice.disconnect(), bot.loop)
        asyncio.run_coroutine_threadsafe(message[ctx.guild].delete(), bot.loop)
        loop = False


@bot.command(pass_context=True, aliases=["PLAY", "p", "P"])
async def play(ctx, *video: str):
    global songStartTime, skipToTime

    # await ctx.channel.purge(limit=1)
    channel = ctx.message.author.voice.channel
    voice = get(bot.voice_clients, guild=ctx.guild)
    song = search(ctx.author.mention, video)

    if voice and voice.is_connected():
        await voice.move_to(channel)
    else:
        voice = await channel.connect()

    if not voice.is_playing():
        songQueue[ctx.guild] = [song]
        musicTitles[ctx.guild] = [video]
        message[ctx.guild] = await ctx.send(embed=song["embed"])
        songStartTime = datetime.now()
        voice.play(discord.FFmpegPCMAudio(executable=ffmpegPathUrl,
                                          source=songQueue[ctx.guild][0]["source"], **ffmpegOptions),
                   after=lambda e: playNext(ctx))
        voice.is_playing()
        skipToTime = 0
    else:
        songQueue[ctx.guild].append(song)
        musicTitles[ctx.guild].append(video)
        await edit_message(ctx)


@bot.command(pass_context=True, aliases=["REPEAT", "r", "R", "again", "AGAIN", "replay", "REPLAY"])
async def repeat(ctx):
    await ctx.channel.purge(limit=1)
    channel = ctx.message.author.voice.channel
    voice = get(bot.voice_clients, guild=ctx.guild)

    try:
        if voice and voice.is_connected():
            await voice.move_to(channel)
        else:
            voice = await channel.connect

        if voice.is_playing():
            songQueue[ctx.guild].insert(1, songQueue[ctx.guild][0])
            musicTitles[ctx.guild].insert(1, musicTitles[ctx.guild][0])
            voice.stop()
        else:
            await ctx.send("Nothing to repeat", delete_after=5)

        await ctx.send("Repeat requested by: {}".format(ctx.message.author), delete_after=5)
        await edit_message(ctx)
    except Exception as e:
        print("Repeat exc:", e)
        await ctx.send("You're not connected to the voice channel or nothing playing now", delete_after=5)


@bot.command(pass_context=True, aliases=["LOOP", "l", "L"])
async def loop(ctx):
    global loop
    await ctx.channel.purge(limit=1)

    if loop is True:
        loop = False
        await ctx.send("**Loop disabled**")
    else:
        loop = True
        await ctx.send("**Loop enabled**")


@bot.command(pass_context=True, aliases=["PAUSE", "stop", "STOP", "resume", "RESUME"])
async def pause(ctx):
    await ctx.channel.purge(limit=1)
    voice = get(bot.voice_clients, guild=ctx.guild)

    if voice.is_connected():
        if voice.is_playing():
            await ctx.send("**Music paused**", delete_after=5)
            voice.pause()
            voice.is_paused()
        else:
            await ctx.send("**Music resumed**", delete_after=5)
            voice.resume()


def timeParse(time):
    seconds = 0
    try:
        seconds = int(time)
    except:
        parts = time.split(":")
        for i in range(len(parts)):
            seconds += int(parts[-i - 1]) * (60 ** i)
    return seconds


@bot.command(pass_context=True, aliases=["SKIP", "s", "S"])
async def skip(ctx, time="0"):
    global skipToTime
    skipped = 0
    requestTime = songStartTime - datetime.now()
    voice = get(bot.voice_clients, guild=ctx.guild)

    try:
        if int(time) is 0:
            await ctx.channel.purge(limit=1)
            if voice.is_playing():
                await ctx.send("Track skipped", delete_after=5)
                skipToTime = 0
                voice.stop()
            else:
                await ctx.send("Nothing is playing", delete_after=5)
        else:
            skipped += int(time) + abs(int(requestTime.total_seconds()))
            skipToTime += skipped
            await skipto(ctx, skipToTime)
    except:
        skipped += timeParse(time) + abs(int(requestTime.total_seconds()))
        skipToTime += skipped
        await skipto(ctx, skipToTime)


@bot.command(pass_context=True, aliases=["SKIPTO", "st", "ST"])
async def skipto(ctx, time):
    global skipToTime
    await ctx.channel.purge(limit=1)
    channel = ctx.message.author.voice.channel
    voice = get(bot.voice_clients, guild=ctx.guild)

    if voice and voice.is_connected():
        await voice.move_to(channel)
    else:
        voice = await channel.connect

    if voice.is_playing():
        songQueue[ctx.guild].insert(1, songQueue[ctx.guild][0])
        musicTitles[ctx.guild].insert(1, musicTitles[ctx.guild][0])
        skipToTime = timeParse(time)
        voice.stop()
    else:
        await ctx.send("Nothing to skip", delete_after=5)

    await ctx.send(f"**Skipped to:** {parseDuration(skipToTime)} **Requested by:** {ctx.message.author}",
                   delete_after=25)
    await edit_message(ctx)


@bot.command(pass_contex=True, aliases=["REMOVE", "rm", "RM"])
async def remove(ctx, position: int):
    if songQueue[ctx.guild][position] and musicTitles[ctx.guild][position]:
        del songQueue[ctx.guild][position], musicTitles[ctx.guild][position]
    else:
        await ctx.send("No such music position in queue", delete_after=5)
    asyncio.run_coroutine_threadsafe(edit_message(ctx), bot.loop)


def chooseEmbedColor(color):
    global embedColor
    embedTitle = f"Your new discord embeds color is *{color}*"

    if color == "blue":
        embedColor = discord.Color.blue()
    elif color == "purple":
        embedColor = discord.Color.purple()
    elif color == "blue-purple":
        embedColor = discord.Color.blurple()
    elif color == "dark-blue":
        embedColor = discord.Color.dark_blue()
    elif color == "dark-gold":
        embedColor = discord.Color.dark_gold()
    elif color == "dark-green":
        embedColor = discord.Color.dark_green()
    elif color == "dark-grey":
        embedColor = discord.Color.dark_grey()
    elif color == "dark-magenta":
        embedColor = discord.Color.dark_magenta()
    elif color == "dark-orange":
        embedColor = discord.Color.dark_orange()
    elif color == "dark-purple":
        embedColor = discord.Color.dark_purple()
    elif color == "dark-red":
        embedColor = discord.Color.dark_red()
    elif color == "dark-teal":
        embedColor = discord.Color.dark_teal()
    elif color == "gold":
        embedColor = discord.Color.gold()
    elif color == "green":
        embedColor = discord.Color.green()
    elif color == "light-grey":
        embedColor = discord.Color.light_grey()
    elif color == "magenta":
        embedColor = discord.Color.magenta()
    elif color == "orange":
        embedColor = discord.Color.orange()
    elif color == "red":
        embedColor = discord.Color.red()
    elif color == "teal":
        embedColor = discord.Color.teal()
    else:
        embedTitle = f"No such color is presented, please choose something from *{commandPrefix}settings " \
                     f"embedColor*\nYour current embed color wasn't changed"
    return embedTitle


@bot.command(pass_context=True, aliases=["SETTINGS", "set", "SET"])
async def settings(ctx, task=None, *args):
    await ctx.channel.purge(limit=1)
    global pauseTime, commandPrefix, embedColor

    if task is None:
        embed = discord.Embed(title=f"Settings command description", description=f"Command pattern is\n"
                                                                                 f"**{commandPrefix}settings [task]**"
                                                                                 f" **[argument]**", color=embedColor) \
            .add_field(name=f"{commandPrefix}settings commandPrefix [symbol]", value="Sets given symbol as command "
                                                                                     "prefix") \
            .add_field(name=f"{commandPrefix}settings embedColor", value=f"Prints all possible embed colors",
                       inline=False) \
            .add_field(name=f"{commandPrefix}settings embedColor [color]", value=f"Sets given color as embed color")
        await ctx.send(embed=embed)
    elif task == "commandPrefix":
        if not args:
            await ctx.send("Please give a prefix after [commandPrefix]", delete_after=5)
        else:
            commandPrefix = args[0]
            bot.command_prefix = commandPrefix
            await ctx.send(f"Your new command prefix is {args[0]}")
    elif task == "embedColor":
        if not args:
            await ctx.send(embed=discord.Embed(title=f"Possible colors are",
                                               description="*blue\npurple\nred\norange\ngreen\nmagenta\nteal\ngold*\n"
                                                           f"*blue-purple\nlight-grey\ndark-blue\ndark-gold\n"
                                                           f"dark-green\ndark-purple\ndark-grey*\n*dark-magenta\n"
                                                           f"dark-orange\ndark-red\ndark-teal*\nUse command "
                                                           f"__*{commandPrefix}settings embedColor dark-purple*__ "
                                                           f" to set embeds color", color=embedColor))
        else:
            embedTitle = chooseEmbedColor(args[0])
            embed = discord.Embed(title=embedTitle, color=embedColor)
            await ctx.send(embed=embed)


def getInfo(query):
    with youtube_dl.YoutubeDL(ydlOptions) as ydl:
        try:
            requests.get(query)
        except:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)["entries"][0]
        else:
            info = ydl.extract_info(query, download=False)
    return info


@bot.command(pass_context=True, aliases=["PLAYLIST", "pl", "PL"])
async def playlist(ctx, task=None, title=None, *music):
    query = ""
    mySqlDB = mysql.connector.connect(
        host=creds[0],
        user=creds[1],
        password=creds[2],
        database=creds[3]
    )

    myCursor = mySqlDB.cursor()

    for i in music:
        query += f"{i} "

    if not task:
        embed = discord.Embed(title="Playlist commands description",
                              description=f"The pattern of command is\n**{commandPrefix}playlist [task] "
                                          f"[playlist title] [music title]**", color=embedColor) \
            .add_field(name=f"{commandPrefix}playlist show", value=f"Shows server playlists", inline=False) \
            .add_field(name=f"{commandPrefix}playlist show [playlist title]", value=f"Shows all tracks from playlist") \
            .add_field(name=f"{commandPrefix}playlist play [playlist title]", value=f"Plays all tracks from playlist",
                       inline=False) \
            .add_field(name=f"{commandPrefix}playlist add [playlist title] [music]", value=f"Adds music to playlist") \
            .add_field(name=f"{commandPrefix}playlist delete [playlist title]", value=f"Deletes playlist",
                       inline=False) \
            .add_field(name=f"{commandPrefix}playlist delete [playlist title] [music]",
                       value=f"Deletes song from playlist")
        await ctx.send(embed=embed)
    elif task == "play":
        if title:
            sqlQuery = "SELECT DISTINCT query FROM playlists WHERE guildId=%s AND playlistTitle=%s"
            values = (ctx.guild.id, title)
            myCursor.execute(sqlQuery, values)
            records = myCursor.fetchall()
            for row in records:
                await play(ctx, row[0])
        else:
            await ctx.send("Please decide which playlist to play")
            await playlist(ctx, "show")
    elif task == "show":
        if not title:
            playlists = ""
            sqlQuery = "SELECT DISTINCT playlistTitle FROM playlists WHERE guildId=%s"
            values = (ctx.guild.id,)
            myCursor.execute(sqlQuery, values)
            records = myCursor.fetchall()
            for row in records:
                playlists += f"*{row[0]}*\n"
            embed = discord.Embed(title="Server playlists", description=f"{playlists}", color=embedColor)
            await ctx.send(embed=embed)
        else:
            songs = ""
            sqlQuery = "SELECT DISTINCT query FROM playlists WHERE guildId=%s AND playlistTitle=%s"
            values = (ctx.guild.id, title)
            myCursor.execute(sqlQuery, values)
            records = myCursor.fetchall()
            for row in records:
                songs += f"{row[0]}\n"
            embed = discord.Embed(title=f"*{title}* playlist music", description=f"{songs}", color=embedColor)
            await ctx.send(embed=embed)
    elif task == "add":
        tags = ""
        sqlQuery = "SELECT DISTINCT playlistTitle FROM playlists WHERE guildId=%s"
        values = (ctx.guild.id,)
        myCursor.execute(sqlQuery, values)
        playlistsAmount = myCursor.fetchall()

        if len(playlistsAmount) < 3:
            sqlQuery = "SELECT DISTINCT query FROM playlists WHERE guildId=%s AND playlistTitle=%s"
            values = (ctx.guild.id, title)
            myCursor.execute(sqlQuery, values)
            songsAmount = myCursor.fetchall()

            if len(songsAmount) < 20:
                info = getInfo(query)

                for i in info["tags"]:
                    if len(tags) < 200:
                        tags += f"{i} "

                sqlQuery = "INSERT INTO playlists (guildId, playlistTitle, query, genre) VALUES (%s, %s, %s, %s)"
                values = (ctx.guild.id, title, query, tags)
                myCursor.execute(sqlQuery, values)
                mySqlDB.commit()
                await ctx.send(f"Song {query} has been added to playlist {title}")
            else:
                await ctx.send(f"Max amount of songs is 20")
        else:
            await ctx.send("Max amount of playlists is 3")
    elif task == "delete":
        if not music:
            sqlQuery = "DELETE FROM playlists WHERE guildId=%s AND playlistTitle=%s LIMIT 1"
            values = (ctx.guild.id, title)
            myCursor.execute(sqlQuery, values)
            mySqlDB.commit()
            await ctx.send(f"Playlist *{title}* is deleted")
        else:
            sqlQuery = "DELETE FROM playlists WHERE guildId=%s AND playlistTitle=%s AND query=%s LIMIT 1"
            values = (ctx.guild.id, title, query)
            myCursor.execute(sqlQuery, values)
            mySqlDB.commit()
            await ctx.send(f"From playlist *{title}* is deleted {query}")
    else:
        await ctx.send("No such command")


@bot.command(pass_context=True, aliases=["HELP", "h", "H"])
async def help(ctx):
    await ctx.channel.purge(limit=1)
    embed = discord.Embed(title="Help", description="Commands", color=embedColor) \
        .add_field(name=f"*{commandPrefix}hello*", value="Greets the user", inline=True) \
        .add_field(name=f"*{commandPrefix}users*", value="Prints number of users on server", inline=True) \
        .add_field(name=f"*{commandPrefix}join*", value="Bot will join voice channel", inline=True) \
        .add_field(name=f"*{commandPrefix}leave*", value="Bot will leave voice channel", inline=True) \
        .add_field(name=f"*{commandPrefix}skip*", value="Plays next track", inline=True) \
        .add_field(name=f"*{commandPrefix}play*", value="Request music with url or song title", inline=True) \
        .add_field(name=f"*{commandPrefix}skip 1:20 or 20*", value="Skips 1 minute 20 seconds of the song or 20 "
                                                                   "seconds, hh:mm:ss format"
                   , inline=False) \
        .add_field(name=f"*{commandPrefix}skipto 1:20 or 20*", value="Song starts playing at this exact time, e.g at 1 "
                                                                     "minute 20 seconds or 20 seconds, hh:mm:ss format"
                   , inline=False) \
        .add_field(name=f"*{commandPrefix}pause*", value="Pauses music", inline=True) \
        .add_field(name=f"*{commandPrefix}replay*", value="Repeats the track", inline=True) \
        .add_field(name=f"*{commandPrefix}queue*", value="Shows queue", inline=True) \
        .add_field(name=f"*{commandPrefix}settings*", value=f"Shows all settings commands") \
        .add_field(name=f"*{commandPrefix}playlist*", value=f"Shows all playlist commands") \
        .add_field(name=f"*{commandPrefix}extendedhelp*\t\t\t\t\t\t*{commandPrefix}aliases*",
                   value="Shows all aliases and some useful information", inline=False) \
        .add_field(name=f"*{commandPrefix}remove*", value=f"Removes song from queue, with given position",
                   inline=False) \
        .add_field(name="CAPS LOCK", value="You can ignore register and use bot with enabled CAPS LOCK", inline=False) \
        .add_field(name="Youtube playlists",
                   value=f'Currently are disabled',# , if you want to enable them, type "*{commandPrefix}settings*"'
                   inline=True)
    await ctx.send(embed=embed)


@bot.command(pass_context=True, aliases=["EXTENDEDHELP", "eh", "Eh", "aliases", "ALIASES"])
async def extendedhelp(ctx):
    await ctx.channel.purge(limit=1)
    embed = discord.Embed(title="Help", description="Extended help commands and aliases", color=embedColor) \
        .add_field(name=f"*{commandPrefix}play*",
                   value=f'Aliases are: "**{commandPrefix}PLAY**", "**{commandPrefix}p**", "**{commandPrefix}P**"',
                   inline=False) \
        .add_field(name=f"*{commandPrefix}pause*",
                   value=f'Aliases are: "**{commandPrefix}PAUSE**", "**{commandPrefix}stop**", '
                         f'"**{commandPrefix}STOP**"', inline=False) \
        .add_field(name=f"*{commandPrefix}help*",
                   value=f'Aliases are: "**{commandPrefix}HELP**", "**{commandPrefix}h**", "**{commandPrefix}H**"',
                   inline=False) \
        .add_field(name=f"*{commandPrefix}repeat*",
                   value=f'Aliases are: "**{commandPrefix}REPEAT**", "**{commandPrefix}r**", "**{commandPrefix}R**", '
                         f'"**{commandPrefix}again**", "**{commandPrefix}AGAIN**", "**{commandPrefix}replay**", '
                         f'"**{commandPrefix}REPLAY**"', inline=False) \
        .add_field(name=f"*{commandPrefix}remove",
                   value=f'Aliases are: "**{commandPrefix}REMOVE**", "**{commandPrefix}rm**", "**{commandPrefix}RM**"',
                   inline=False) \
        .add_field(name=f"*{commandPrefix}skip*",
                   value=f'Aliases are: "**{commandPrefix}SKIP**", "**{commandPrefix}s**", "**{commandPrefix}S**"',
                   inline=False) \
        .add_field(name=f"*{commandPrefix}skipto*",
                   value=f'Aliases are: "**{commandPrefix}SKIPTO**", "**{commandPrefix}st**", "**{commandPrefix}ST**"',
                   inline=False) \
        .add_field(name=f"*{commandPrefix}settings*",
                   value=f'Aliases are: "**{commandPrefix}SETTINGS**", "**{commandPrefix}set**", '
                         f'"**{commandPrefix}SET**"', inline=False) \
        .add_field(name=f"*{commandPrefix}playlist*",
                   value=f'Aliases are: "**{commandPrefix}PLAYLIST**", "**{commandPrefix}pl**", '
                         f'"**{commandPrefix}PL**"', inline=False) \
        .add_field(name=f"*{commandPrefix}extendedhelp*",
                   value=f'Aliases are: "**{commandPrefix}EXTENDEDHELP**", "**{commandPrefix}eh**", '
                         f'"**{commandPrefix}EH**", "**{commandPrefix}aliases**", "**{commandPrefix}ALIASES**"',
                   inline=False) \
        .add_field(name="Issues", value=f'If bot stuck at voice channel, use command "**{commandPrefix}leave**" it '
                                        f'will clear cache also you can disconnect bot from voice chat and then test '
                                        f'with "**{commandPrefix}join**" command', inline=False)
    await ctx.send(embed=embed)


@bot.command(pass_context=True)
async def hello(ctx):
    await ctx.send(f"Hi {ctx.author}. Your server id is {ctx.guild.id}")


@bot.command(pass_context=True)
async def users(ctx):
    await ctx.send("Number of users on server: {}".format(ctx.guild.member_count))


@bot.command(pass_context=True, aliases=["QUEUE", "q", "Q"])
async def queue(ctx, page=1):
    await ctx.channel.purge(limit=1)
    voice = get(bot.voice_clients, guild=ctx.guild)
    playing, content, pg, iterator, queueSize = "", "", 0, 0, 5
    page = page - 1

    if voice and voice.is_playing:
        playing = f"[{songQueue[ctx.guild][0]['title']}]({songQueue[ctx.guild][0]['webpage_url']})"
    else:
        await ctx.send("Nothing playing", delete_after=10)

    if len(songQueue[ctx.guild]) > 1:
        for i in songQueue[ctx.guild][1:]:
            iterator += 1
            pg = iterator // queueSize + 1

            if page == iterator // queueSize:
                content += "\n".join([f" **{songQueue[ctx.guild].index(i)}:** [{i['title']}]({i['webpage_url']})\n"
                                      f"**Requested by:** {ctx.author.mention}   **Duration:** {i['duration']}\n"])
        if pg > 1:
            content += "\n".join([f"**Page:** {page + 1}/{pg}"])
    else:
        content = "No queued songs"

    embed = (discord.Embed(title="Music queue", color=embedColor)
             .add_field(name="Playing now: ", value=playing, inline=False)
             .add_field(name="Requested by", value=f"{ctx.author.mention}", inline=True)
             .add_field(name="Duration", value=songQueue[ctx.guild][0]['duration'], inline=True)
             .add_field(name="Queued: ", value=content, inline=False)
             .set_thumbnail(url=songQueue[ctx.guild][0]["thumbnail"]))
    await ctx.send(embed=embed)


@bot.command(pass_context=True, aliases=["VOLUME", "vol", "VOL"])
async def volume(ctx, volume: int):
    await ctx.channel.purge(limit=1)
    voice = get(bot.voice_clients, guild=ctx.guild)
    voice.source = discord.PCMVolumeTransformer(voice.source)
    voice.source.volume = volume / 100
    await ctx.send(f"Volume changed to {volume}%", delete_after=15)


@play.error
@repeat.error
@leave.error
@pause.error
@skip.error
@skipto.error
@queue.error
@settings.error
@playlist.error
@remove.error
@volume.error
async def errorHandler(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        print(error)
        await ctx.send("You're not connected to the voice channel or nothing playing now", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Command requires additional info", delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("No such command", delete_after=5)
    elif isinstance(error, commands.ConversionError):
        await ctx.send("Sorry, requested video can't be decoded, try one more time please", delete_after=5)
    elif isinstance(error, commands.TooManyArguments):
        await ctx.send("Too many arguments, please check if everything is okay", delete_after=5)
    elif isinstance(error, ValueError):
        await ctx.send("Please enter correct value", delete_after=5)
    else:
        print("Error handler:", error)


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    perms = discord.Permissions(permissions=8)
    invite_link = discord.utils.oauth_url(bot.user.id, permissions=perms)
    print(f"Use this link to add bot to your server: {invite_link}")

    activity = discord.Game(name=f"{commandPrefix}help", type=3)
    await bot.change_presence(activity=activity)

    for guild in bot.guilds:
        print("{} is connected to the following guild: {}. Guild id: {}".format(bot.user, guild.name, guild.id))


# todo join, rejoin, wait after everyone leaves, leave after no one mentions for some time || task ended
# @bot.event
# async def on_voice_state_update(member, before, after):
#     print("Channel {}\n {}\n {}\n".format(member, before, after))
#     # if after.channel is None:
#     #     asyncio.sleep(2)


# @bot.event
# async def on_member_join(member):
#     global joined
#     joined += 1
#     # for channel in member.guild.channels:
#     #     if str(channel) == "general":
#     #         print("Someone connected")
#     await member.create_dm()
#     await member.dm_channel.send(f'Hi {member.name}, welcome to my Discord server!')


# @bot.event
# async def on_server_join():
#     pass


@bot.event
async def on_member_update(before, after):
    nickname = after.nick
    if nickname:
        if nickname.lower().count("dream") > 0:
            lastNickname = before.nick
            if lastNickname:
                await after.edit(nick=lastNickname)
            else:
                await after.edit(nick="Nickname dream is reserved by bot, please change your role or nickname")


async def clearDatabase():
    guilds = []
    await bot.wait_until_ready()

    for guildid in bot.guilds:
        guilds.append(guildid.id)

    while not bot.is_closed():
        try:
            mySqlDB = mysql.connector.connect(
                host=creds[0],
                user=creds[1],
                password=creds[2],
                database=creds[3]
            )

            myCursor = mySqlDB.cursor()
            sqlQuery = "SELECT DISTINCT guildId FROM playlists"
            # values = (guild.id,)
            myCursor.execute(sqlQuery)
            records = myCursor.fetchall()
            for guild in records:
                if int(guild[0]) not in guilds:
                    sqlQuery = "DELETE FROM playlists WHERE guildId=%s"
                    values = (guild[0],)
                    myCursor.execute(sqlQuery, values)
                    mySqlDB.commit()
            await asyncio.sleep(86400)
        except Exception as e:
            print("Clear database exc: ", e)


bot.loop.create_task(clearDatabase())
# bot.loop.create_task(update_stats())
bot.run(token)
