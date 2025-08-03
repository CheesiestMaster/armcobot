from typing import Optional, Type, Union, Any
import discord
from discord.ui import View

class MessageManager:
    """
    A simplified class to manage a Discord message with optional View and Embed.
    
    Args:
        destination: The Interaction or TextChannel to send messages to.
        view_type: Optional Type[View] that is self-building.
        embed_type: Optional Type[discord.Embed] that is self-building.
    """
    def __init__(
        self,
        destination: Union[discord.Interaction, discord.abc.Messageable],
        view_type: Optional[Type[View]] = None,
        embed_type: Optional[Type[discord.Embed]] = None,
    ):
        self.destination = destination
        self.view = view_type() if view_type else None
        self.embed = embed_type() if embed_type else None
        self.message = None

    async def send_message(self, embed: Optional[discord.Embed] = None, view: Optional[View] = None, **kwargs: Any):
        """
        Sends the message to the destination.
        Automatically determines whether to use Interaction.response or Channel.send.
        
        Additional kwargs are passed to the send method.
        """
        if embed:
            self.embed = embed
        if view:
            self.view = view
        if isinstance(self.destination, discord.Interaction):
            if not self.destination.response.is_done():
                await self.destination.response.send_message(embed=self.embed, view=self.view, **kwargs)
                self.message = await self.destination.original_response()
            else:
                self.message = await self.destination.followup.send(embed=self.embed, view=self.view, **kwargs)
        else:
            self.message = await self.destination.send(embed=self.embed, view=self.view, **kwargs)

    async def update_message(self, view: Optional[View] = None, embed: Optional[discord.Embed] = None, **kwargs: Any):
        """
        Updates the existing message with the current View and Embed.
        
        Additional kwargs are passed to the edit method.
        """
        if view:
            self.view = view
        if embed:
            self.embed = embed
        if self.message:
            await self.message.edit(embed=self.embed, view=self.view, **kwargs)
        else:
            raise ValueError("No message to update. Call `send_message` first.")
        
    async def delete_message(self):
        if not self.message:
            raise ValueError("No message to delete. Call `send_message` first.")
        if isinstance(self.destination, discord.Interaction):
            await self.destination.delete_original_response()
        else:
            await self.message.delete()
        self.message = None
        self.destination = None
