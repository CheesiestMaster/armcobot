from typing import Any, Optional, Type, Union

import discord
from discord.ui import View

class MessageManager:
    """
    Manages sending Discord messages to an Interaction or Messageable
    (e.g. channel), with optional persistent View and Embed. Chooses
    response.send_message, followup.send, or channel.send as appropriate.
    """

    def __init__(
        self,
        destination: Union[discord.Interaction, discord.abc.Messageable],
        view_type: Optional[Type[View]] = None,
        embed_type: Optional[Type[discord.Embed]] = None,
    ):
        """
        Create a MessageManager for a destination (Interaction or channel).

        Args:
            destination: Where to send messages (Interaction or Messageable).
            view_type: Optional View class; instantiated and used for sends.
            embed_type: Optional Embed class; instantiated and used for sends.
        """

        self.destination = destination
        self.view = view_type() if view_type else None
        self.embed = embed_type() if embed_type else None
        self.message = None

    async def send_message(self, embed: Optional[discord.Embed] = None, view: Optional[View] = None, **kwargs: Any):
        """
        Send a message to the destination. Uses response.send_message,
        followup.send, or channel.send depending on destination state.
        Optional embed and view; extra kwargs are passed to the send call.
        """

        if embed:
            self.embed = embed
        if view:
            self.view = view
        # Prepare kwargs, only including embed and view if they're not None
        send_kwargs = kwargs.copy()
        if self.embed is not None:
            send_kwargs['embed'] = self.embed
        if self.view is not None:
            send_kwargs['view'] = self.view

        if isinstance(self.destination, discord.Interaction):
            if not self.destination.response.is_done():
                await self.destination.response.send_message(**send_kwargs)
                self.message = await self.destination.original_response()
            else:
                self.message = await self.destination.followup.send(**send_kwargs)
        else:
            if self.destination is None:
                raise ValueError("Destination is None")
            self.message = await self.destination.send(**send_kwargs)

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
            # Prepare kwargs, only including embed and view if they're not None
            edit_kwargs = kwargs.copy()
            if self.embed is not None:
                edit_kwargs['embed'] = self.embed
            if self.view is not None:
                edit_kwargs['view'] = self.view
            await self.message.edit(**edit_kwargs)
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
