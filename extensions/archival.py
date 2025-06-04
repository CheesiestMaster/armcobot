import asyncio
from logging import getLogger
import discord
from discord.ext.commands import GroupCog, Bot
from discord import Interaction, app_commands as ac
from typing import Optional, Dict, Any
from discord import Message, User, Attachment, Embed, Reaction
import json
from utils import is_management_no_notify

logger = getLogger(__name__)



class Archival(GroupCog):
    @ac.command(name="archive", description="Archive a channel")
    @ac.check(is_management_no_notify)
    async def archive(self, interaction: Interaction, channel: discord.TextChannel|discord.Thread):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(f"Archiving {channel.mention}")
        logger.info(f"Archiving {channel.name} of type {type(channel)}")
        # create a task to archive the channel so this context can be deleted
        asyncio.create_task(self.archive_worker(channel, interaction.user))

    async def archive_worker(self, channel: discord.TextChannel|discord.Thread, author: discord.Member):
        with open(f"archives/{channel.id}.json", "w") as f:
            f.write("[")
            async for message in channel.history(limit=None, oldest_first=True):
                f.write(json.dumps(MessageSerializer.serialize_message(message)) + ",")
            # remove the last comma
            f.seek(f.tell() - 1)
            f.truncate()
            f.write("]")
        await author.send(f"Archived {channel.mention}")

class MessageSerializer:
    @staticmethod
    def serialize_message(message: Message) -> Dict[str, Any]:
        """Serialize a Discord Message object to match the Discord API message schema."""
        return {
            "id": str(message.id),
            "type": message.type.value if hasattr(message, 'type') and message.type else None,
            "content": message.content if hasattr(message, 'content') else None,
            "channel_id": str(message.channel.id) if hasattr(message, 'channel') and message.channel else None,
            "author": MessageSerializer.serialize_user(message.author) if hasattr(message, 'author') else None,
            "attachments": [MessageSerializer.serialize_attachment(attachment) for attachment in message.attachments] if hasattr(message, 'attachments') else None,
            "embeds": [MessageSerializer.serialize_embed(embed) for embed in message.embeds] if hasattr(message, 'embeds') else None,
            "mentions": [MessageSerializer.serialize_user(user) for user in message.mentions] if hasattr(message, 'mentions') else None,
            "mention_roles": [str(role.id) for role in message.role_mentions] if hasattr(message, 'role_mentions') else None,
            "pinned": message.pinned if hasattr(message, 'pinned') else None,
            "mention_everyone": message.mention_everyone if hasattr(message, 'mention_everyone') else None,
            "tts": message.tts if hasattr(message, 'tts') else None,
            "timestamp": message.created_at.isoformat() if hasattr(message, 'created_at') and message.created_at else None,
            "edited_timestamp": message.edited_at.isoformat() if hasattr(message, 'edited_at') and message.edited_at else None,
            "flags": message.flags.value if hasattr(message, 'flags') and message.flags else None,
            "components": [],  # Message components (buttons, etc.) if any
            "webhook_id": str(message.webhook_id) if hasattr(message, 'webhook_id') else None,
            "application_id": str(message.application_id) if hasattr(message, 'application_id') else None,
            "interaction": MessageSerializer.serialize_interaction(message.interaction_metadata) if hasattr(message, 'interaction_metadata') else None,
            "thread": MessageSerializer.serialize_thread(message.thread) if hasattr(message, 'thread') else None,
            "referenced_message": MessageSerializer.serialize_message(message.reference.resolved) if hasattr(message, 'reference') and hasattr(message.reference, 'resolved') and message.reference.resolved else None,
            "reactions": [MessageSerializer.serialize_reaction(reaction) for reaction in message.reactions] if hasattr(message, 'reactions') else None,
            "activity": MessageSerializer.serialize_activity(message.activity) if hasattr(message, 'activity') else None,
            "application": MessageSerializer.serialize_application(message.application) if hasattr(message, 'application') else None,
            "message_reference": MessageSerializer.serialize_message_reference(message.reference) if hasattr(message, 'reference') else None,
            "guild_id": str(message.guild.id) if hasattr(message, 'guild') and message.guild else None,
        }

    @staticmethod
    def serialize_user(user: User) -> Dict[str, Any]:
        """Serialize a Discord User object."""
        return {
            "id": str(user.id),
            "username": user.name,
            "discriminator": user.discriminator,
            "avatar": user.avatar.key if user.avatar else None,
            "bot": user.bot,
            "system": user.system if hasattr(user, 'system') else False,
            "mfa_enabled": user.mfa_enabled if hasattr(user, 'mfa_enabled') else None,
            "banner": user.banner.key if user.banner else None,
            "accent_color": user.accent_color,
            "locale": user.locale if hasattr(user, 'locale') else None,
            "verified": user.verified if hasattr(user, 'verified') else None,
            "email": user.email if hasattr(user, 'email') else None,
            "flags": user.public_flags.value if hasattr(user, 'public_flags') else None,
            "premium_type": user.premium_type if hasattr(user, 'premium_type') else None,
        }

    @staticmethod
    def serialize_attachment(attachment: Attachment) -> Dict[str, Any]:
        """Serialize a Discord Attachment object."""
        return {
            "id": str(attachment.id),
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "size": attachment.size,
            "url": attachment.url,
            "proxy_url": attachment.proxy_url,
            "height": attachment.height,
            "width": attachment.width,
            "ephemeral": attachment.ephemeral if hasattr(attachment, 'ephemeral') else False,
        }

    @staticmethod
    def serialize_embed(embed: Embed) -> Dict[str, Any]:
        """Serialize a Discord Embed object."""
        return {
            "title": embed.title,
            "type": embed.type,
            "description": embed.description,
            "url": embed.url,
            "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
            "color": embed.color.value if embed.color else None,
            "footer": {
                "text": embed.footer.text,
                "icon_url": embed.footer.icon_url,
            } if embed.footer else None,
            "image": {
                "url": embed.image.url,
                "proxy_url": embed.image.proxy_url,
                "height": embed.image.height,
                "width": embed.image.width,
            } if embed.image else None,
            "thumbnail": {
                "url": embed.thumbnail.url,
                "proxy_url": embed.thumbnail.proxy_url,
                "height": embed.thumbnail.height,
                "width": embed.thumbnail.width,
            } if embed.thumbnail else None,
            "video": {
                "url": embed.video.url,
                "proxy_url": embed.video.proxy_url,
                "height": embed.video.height,
                "width": embed.video.width,
            } if embed.video else None,
            "provider": {
                "name": embed.provider.name,
                "url": embed.provider.url,
            } if embed.provider else None,
            "author": {
                "name": embed.author.name,
                "url": embed.author.url,
                "icon_url": embed.author.icon_url,
                "proxy_icon_url": embed.author.proxy_icon_url,
            } if embed.author else None,
            "fields": [
                {
                    "name": field.name,
                    "value": field.value,
                    "inline": field.inline,
                }
                for field in embed.fields
            ],
        }

    @staticmethod
    def serialize_reaction(reaction: Reaction) -> Dict[str, Any]:
        """Serialize a Discord Reaction object."""
        return {
            "count": reaction.count,
            "me": reaction.me,
            "emoji": {
                "id": str(reaction.emoji.id) if hasattr(reaction.emoji, 'id') else None,
                "name": reaction.emoji.name if hasattr(reaction.emoji, 'name') else reaction.emoji,
                "animated": reaction.emoji.animated if hasattr(reaction.emoji, 'animated') else False,
            },
        }

    @staticmethod
    def serialize_interaction(interaction: Any) -> Optional[Dict[str, Any]]:
        """Serialize a Discord Interaction object."""
        if not interaction:
            return None
        return {
            "id": str(interaction.id),
            "type": interaction.type.value if hasattr(interaction, 'type') and interaction.type else None,
            "name": interaction.name if hasattr(interaction, 'name') and interaction.name else None,
            "user": MessageSerializer.serialize_user(interaction.user) if hasattr(interaction, 'user') and interaction.user else None,
            "guild_id": str(interaction.guild_id) if hasattr(interaction, 'guild_id') else None,
            "channel_id": str(interaction.channel_id) if hasattr(interaction, 'channel_id') else None,
        }

    @staticmethod
    def serialize_thread(thread: Any) -> Optional[Dict[str, Any]]:
        """Serialize a Discord Thread object."""
        if not thread:
            return None
        return {
            "id": str(thread.id),
            "name": thread.name,
            "type": thread.type.value,
            "guild_id": str(thread.guild_id) if hasattr(thread, 'guild_id') else None,
            "parent_id": str(thread.parent_id) if hasattr(thread, 'parent_id') else None,
            "owner_id": str(thread.owner_id) if hasattr(thread, 'owner_id') else None,
            "last_message_id": str(thread.last_message_id) if hasattr(thread, 'last_message_id') else None,
            "message_count": thread.message_count if hasattr(thread, 'message_count') else None,
            "member_count": thread.member_count if hasattr(thread, 'member_count') else None,
            "rate_limit_per_user": thread.rate_limit_per_user if hasattr(thread, 'rate_limit_per_user') else None,
        }

    @staticmethod
    def serialize_activity(activity: Any) -> Optional[Dict[str, Any]]:
        """Serialize a Discord Activity object."""
        if not activity:
            return None
        return {
            "type": activity.type.value,
            "name": activity.name,
            "url": activity.url,
            "created_at": activity.created_at.isoformat() if hasattr(activity, 'created_at') else None,
            "timestamps": activity.timestamps._to_dict() if hasattr(activity, 'timestamps') else None,
            "application_id": str(activity.application_id) if hasattr(activity, 'application_id') else None,
            "details": activity.details,
            "state": activity.state,
            "emoji": {
                "name": activity.emoji.name,
                "id": str(activity.emoji.id) if hasattr(activity.emoji, 'id') else None,
                "animated": activity.emoji.animated if hasattr(activity.emoji, 'animated') else False,
            } if activity.emoji else None,
        }

    @staticmethod
    def serialize_application(application: Any) -> Optional[Dict[str, Any]]:
        """Serialize a Discord Application object."""
        if not application:
            return None
        return {
            "id": str(application.id),
            "name": application.name,
            "icon": application.icon.key if application.icon else None,
            "description": application.description,
            "cover_image": application.cover_image.key if application.cover_image else None,
        }

    @staticmethod
    def serialize_message_reference(reference: Any) -> Optional[Dict[str, Any]]:
        """Serialize a Discord MessageReference object."""
        if not reference:
            return None
        return {
            "message_id": str(reference.message_id) if reference.message_id else None,
            "channel_id": str(reference.channel_id) if reference.channel_id else None,
            "guild_id": str(reference.guild_id) if reference.guild_id else None,
            "fail_if_not_exists": reference.fail_if_not_exists if hasattr(reference, 'fail_if_not_exists') else None,
        }

bot: Bot = None
async def setup(_bot: Bot):
    global bot
    bot = _bot
    await bot.add_cog(Archival(bot))

async def teardown():
    bot.remove_cog(Archival.__name__) # remove_cog takes a string, not a class