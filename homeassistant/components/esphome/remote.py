"""Support for ESPHome remotes."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from aioesphomeapi import EntityState, RemoteCommand
from aioesphomeapi.model import RemoteInfo
from remoteprotocols import ProtocolRegistry

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EsphomeEntity, platform_async_setup_entry

REGISTRY = ProtocolRegistry()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up ESPHome remote based on a config entry."""
    await platform_async_setup_entry(
        hass,
        entry,
        async_add_entities,
        component_key="remote",
        info_type=RemoteInfo,
        entity_type=EsphomeRemote,
        state_type=EntityState,
    )


class EsphomeRemote(EsphomeEntity[RemoteInfo, EntityState], RemoteEntity):
    """A remote implementation for ESPHome."""

    @callback
    def _on_device_update(self) -> None:
        """Update the entity state when device info has changed."""
        # This override the EsphomeEntity method as the remote entity
        # never gets a state update.
        self._on_state_update()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send commands to a device."""

        for cmd_str in command:

            cmd = REGISTRY.convert(cmd_str, protocols=["duration"])

            if not cmd:
                raise ValueError("Command cannot be converted to 'duration' raw format")

            repeat = kwargs["num_repeats"] if "num_repeats" in kwargs else 1
            wait = int(kwargs["delay_secs"] * 1000) if "delay_secs" in kwargs else 0

            await self._client.remote_command(
                self._static_info.key,
                RemoteCommand.SEND,
                cmd[0].protocol.name,
                cmd[0].args,
                repeat,
                wait,
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._client.remote_command(
            self._static_info.key, RemoteCommand.TURNON, "", [], 1, 0
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._client.remote_command(
            self._static_info.key, RemoteCommand.TURNOFF, "", [], 1, 0
        )
