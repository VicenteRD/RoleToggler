import discord
from discord import TextChannel
from discord.ext import commands

from redbot.core import checks

from redbot.core.json_io import JsonIO, PRETTY

from pathlib import Path

DATA_PATH = Path.cwd() / "data" / "role_toggler"
DEFAULT_SETTINGS = {
    'message': "Add a reaction to opt in/out of livestream notifications!",
}


class DataInterface(JsonIO):
    """ Wrapper for the JsonIO class provided by RedBot
    """

    def __init__(self, path: Path, file_name: str):
        super().__init__(path / file_name)

        self.name = file_name.split('.')[0]

        self._data = None
        self._loaded = False

    def load(self, default):
        if not self.path.exists():
            print("Creating default {} file...".format(self.name))
            self._data = default
            self.save()
        else:
            self._data = super()._load_json()

        self._loaded = True

        return self

    def save(self):
        super()._save_json(self._data, PRETTY)

    def read(self, key=None):
        if self._data is None:
            return None
        if key is not None and not isinstance(key, str):
            key = str(key)

        if key is None:
            return self._data

        value = self._data
        for sub_key in key.split('.'):
            if isinstance(value, dict):
                value = value[sub_key]
            elif isinstance(value, list):
                value = value[int(sub_key)]
            else:
                break

        return value

    def write(self, key, value):
        if self._data is None:
            self._data = {}

        key_list = key.split('.')
        last_key = key_list.pop()

        sub_dict = self._data

        if key_list:
            for sub_key in key_list:
                if not isinstance(sub_dict, dict):
                    break
                sub_dict = sub_dict[sub_key]

        sub_dict[last_key] = value
        return self

    def set(self, obj):
        if isinstance(obj, dict) or isinstance(obj, list):
            self._data = obj
        return self

    def is_loaded(self):
        return self._loaded


class RoleToggler:
    """ A custom cog that lets users opt in/out
        of a certain role. Useful for letting users choose whether
        they want to be notified about a livestream going live.
    """

    def __init__(self, bot):
        self.bot = bot

        self._messages = {}

        self._settings = None
        self._reload_settings()

    async def setup(self):
        """ Sets the extensions up, recording the messages given in settings
            and adding reactions to them.
        """

        for server in self.bot.guilds:
            if str(server.id) not in self._settings.read():
                continue

            channel = self._get_channel(server.id)
            message_id = self._settings.read(str(server.id) + '.message_id')

            if message_id is None:
                message = await channel.send(self._settings.read('message'))
            else:
                message = await channel.get_message(message_id)

            await message.add_reaction(self._get_emoji(server.id))

            self._messages[server.id] = message.id

    @commands.group()
    @checks.admin_or_permissions()
    async def rtoggler(self, ctx):
        """ Commands that let you setup a message reaction to let users opt
            in/out of a certain role. Useful for letting users choose whether
            they want to be notified about a livestream going live or not.
            You will need to execute all 3 commands at least once to properly
            set things up. Order is irrelevant!

                role: Specifies the toggle-able role.
                message: Specifies the message in which the reaction will be
                    available.
                emoji: Gives an emoji to use as the reaction.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send("You're not the only one, but you're doing things wrong...")

    @rtoggler.command(name="reload")
    async def _reload(self, ctx):
        self._reload_settings()

        await ctx.send('Successfully reloaded settings.')

    @rtoggler.command(name="role")
    async def _set_role(self, ctx, role_id: int):
        """ Specifies the ID of the role that will be given or taken
            from users when reacting to the specified message with the given
            emoji.

            :param role_id: The ID of the role to give or take from users.
                To get the ID, make sure you can @mention the role and
                write \@Role-Name in chat (Will mention the role).
        """
        server = ctx.guild
        role = discord.utils.get(server.roles, id=role_id)

        if role is None:
            await ctx.send("Invalid role ID.")
            return

        self._settings.write(str(server.id) + '.role_id', role.id).save()

        await ctx.send('Successfully registered the role.')

    @rtoggler.command(name="emoji")
    async def _set_emoji(self, ctx, emoji):
        """ Defines the emoji to use in this server as the one users have to
            react with to get the role given or removed

            :param emoji: The emoji to use.
        """
        server = ctx.guild
        if str(server.id) not in self._settings.read():
            self._settings.write(str(server.id), {})

        self._settings.write(str(server.id) + '.emoji', emoji).save()

        if server.id in self._messages:
            channel = self._get_channel(server.id)
            message = await channel.get_message(self._messages[server.id])
            await message.clear_reactions()
            await message.add_reaction(emoji)

        await ctx.send("Successfully set the emoji for this server")

    @rtoggler.command(name="message")
    async def _set_message(self, ctx, message_id, channel_id=None):
        """ Sets the message which the bot will monitor for reactions.
            If the channel in which the message changes, please specify
            the new channel's ID as well (or if it is the first time setting
            things up)

            :param message_id: The ID of the message.
            :param channel_id: Optional. The ID of the channel the message
                is in. If setting up for the first time, it must be provided.
                The message MUST BE within this channel. If a `message_id` is
                provided for a message outside the specified channel, things
                will break.
        """

        server = ctx.guild
        channel_id_key = str(server.id) + '.channel_id'

        if str(server.id) not in self._settings.read():
            self._settings.write(str(server.id), {})

        if channel_id_key not in self._settings.read():
            if channel_id is None:
                ctx.send("Channel is not set, please specify one.")
                return
            else:
                self._settings.write(channel_id_key, None)

        channel = self._get_channel(server.id)

        if channel is not None and server.id in self._messages:
            message = await channel.get_message(self._messages[server.id])
            await message.clear_reactions()

        if channel_id is not None:
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                await ctx.send('Invalid channel ID.')
                return

            self._settings.write(channel_id_key, int(channel_id))

        message = await channel.get_message(message_id)
        if message is None:
            await ctx.send('Invalid message ID.')
            return

        self._settings.write(str(server.id) + '.message_id', int(message_id))

        self._settings.save()

        self._messages[server.id] = int(message_id)

        await message.clear_reactions()

        if 'emoji' in self._settings.read(str(server.id)):
            await message.add_reaction(self._get_emoji(server.id))

        await ctx.send('Successfully configured the message for this server.')

    async def on_raw_reaction_add(self, emoji, message_id, channel_id, user_id):
        if user_id == self.bot.user.id:
            return

        channel = self.bot.get_channel(channel_id)
        if (not isinstance(channel, TextChannel)) or channel.guild is None or\
                message_id not in self._messages.values():
            return

        server = channel.guild
        user = server.get_member(user_id)
        message = await channel.get_message(message_id)

        await message.remove_reaction(emoji, user)

        if 'role_id' not in self._settings.read(str(server.id)):
            return

        role_id = self._settings.read(str(server.id) + '.role_id')
        toggled_role = discord.utils.get(server.roles, id=role_id)

        if toggled_role is None or \
                emoji.is_custom_emoji() or \
                emoji.name != self._settings.read(str(server.id) + '.emoji'):
            return

        if toggled_role in user.roles:
            await user.remove_roles(toggled_role)
            if user.dm_channel is None:
                await user.create_dm()
            await user.dm_channel.send(self._settings.read('remove_dm').format(user.display_name, toggled_role.name))
        else:
            await user.add_roles(toggled_role)
            if user.dm_channel is None:
                await user.create_dm()
            await user.dm_channel.send(self._settings.read('add_dm').format(user.display_name, toggled_role.name))

    async def _clear_reactions(self):
        for server_id, message_id in self._messages.items():
            message = await self._get_channel(server_id).get_message(message_id)
            await message.clear_reactions()

    def _reload_settings(self):
        self._settings = DataInterface(DATA_PATH, 'settings.json') \
            .load(DEFAULT_SETTINGS)

    def _get_channel(self, server_id):
        return self.bot.get_channel(
            self._settings.read(str(server_id) + '.channel_id')
        )

    def _get_emoji(self, server_id):
        return self._settings.read(str(server_id) + '.emoji')

    def __unload(self):
        self.bot.loop.create_task(self._clear_reactions())


def setup(bot):
    role_manager = RoleToggler(bot)
    bot.add_cog(role_manager)
    bot.loop.create_task(role_manager.setup())
