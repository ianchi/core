"""Support for remote controlled media player."""
from __future__ import annotations

import logging
from typing import Any

from remotecodes import get_codes
from remotecodes.schema import media_player, validate_source
import voluptuous as vol

from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_SELECT_SOUND_MODE,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_STEP,
)
from homeassistant.components.media_player.errors import MediaPlayerException
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    CONF_UNIQUE_ID,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)

CONF_REMOTE_DEVICE = "remote_device"
CONF_CODES_SOURCE = "codes_source"
CONF_SOURCE_NAMES = "source_names"
CONF_SOUND_MODES_NAMES = "sound_modes_names"

DEFAULT_NAME = "Remote Controlled Media Player"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Required(CONF_REMOTE_DEVICE): cv.entity_id,
        vol.Required(CONF_CODES_SOURCE): validate_source,
        vol.Optional(CONF_SOURCE_NAMES): media_player.SOURCES_SCHEMA,
        vol.Optional(CONF_SOUND_MODES_NAMES): media_player.SOUND_MODES_SCHEMA,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    _discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Remote platform."""

    try:
        codes = get_codes(config.get(CONF_CODES_SOURCE), "media_player")  # type:ignore
        entity = RemoteMediaPlayerDevice(config, codes["media_player"])
        async_add_entities([entity])

    except vol.Invalid as err:
        _LOGGER.error(
            "Error reading codes file '%s': %s", config.get(CONF_CODES_SOURCE), err.msg
        )


class RemoteMediaPlayerDevice(MediaPlayerEntity):
    """Representation of a Remote controlled media player device."""

    _remote_id: str | None = None
    _codes: dict[str, Any]

    def __init__(self, config: ConfigType, codes: dict[str, Any]) -> None:
        """Initialize the Remote Media Player."""

        self._remote_id = config.get(CONF_REMOTE_DEVICE)
        self._codes = codes

        # TODO: option to use external sensor to get actual state
        self._attr_assumed_state = True

        self._attr_name = config.get(CONF_NAME)
        if CONF_UNIQUE_ID in config:
            self._attr_unique_id = config.get(CONF_UNIQUE_ID)

        self._attr_state = STATE_OFF

        print(codes)
        # define features according to available codes
        self._attr_supported_features = 0
        if "power" in codes:
            self._attr_supported_features |= SUPPORT_TURN_ON | SUPPORT_TURN_OFF

        if "volume" in codes:
            if "up" in codes["volume"]:
                self._attr_supported_features |= SUPPORT_VOLUME_STEP
            if "mute_on" in codes["volume"] or "mute_toggle" in codes["volume"]:
                self._attr_supported_features |= SUPPORT_VOLUME_MUTE

        if "sources" in codes:
            self._attr_supported_features |= SUPPORT_SELECT_SOURCE
            # TODO: rename sources
            self._attr_source_list = list(codes["sources"].keys())

        if "sound_modes" in codes:
            self._attr_supported_features |= SUPPORT_SELECT_SOUND_MODE
            # TODO: rename sound_modes
            self._attr_sound_mode_list = list(codes["sound_modes"].keys())

        # TODO: play / next track / prev track

    async def _async_send_command(self, commands: str | list[str]) -> None:
        """Send commands using the associated remote."""

        data = {
            ATTR_ENTITY_ID: self._remote_id,
            "command": commands,
        }

        await self.hass.services.async_call("remote", "send_command", data)

    async def async_turn_off(self) -> None:
        """Turn the media player off."""

        if not (self._attr_supported_features & SUPPORT_TURN_OFF):
            raise NotImplementedError()

        command = self._codes["power"].get("off", self._codes["power"].get("toggle"))
        await self._async_send_command(command)
        self._attr_state = STATE_OFF

    async def async_turn_on(self) -> None:
        """Turn the media player on."""

        if not (self._attr_supported_features & SUPPORT_TURN_ON):
            raise NotImplementedError()

        command = self._codes["power"].get("on", self._codes["power"].get("toggle"))
        await self._async_send_command(command)
        self._attr_state = STATE_ON

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""

        if not (self.support_volume_mute):
            raise NotImplementedError()

        mode = "mute_on" if mute else "mute_off"
        command = self._codes["volume"].get(mode, self._codes["volume"]["mute_toggle"])

        await self._async_send_command(command)

    async def async_volume_down(self) -> None:
        """Turn volume down for media player."""

        if not (self._attr_supported_features & SUPPORT_VOLUME_STEP):
            raise NotImplementedError()

        command = self._codes["volume"]["down"]
        await self._async_send_command(command)

    async def async_volume_up(self) -> None:
        """Turn volume down for media player."""

        if not (self._attr_supported_features & SUPPORT_VOLUME_STEP):
            raise NotImplementedError()

        command = self._codes["volume"]["up"]
        await self._async_send_command(command)

    async def async_select_source(self, source: str) -> None:
        """Select input source."""

        if not (self.support_select_source):
            raise NotImplementedError()

        if source not in self._codes["sources"]:
            raise MediaPlayerException(f"Invalid source '{source}'")

        command = self._codes["sources"][source]
        await self._async_send_command(command)

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select sound mode."""

        if not (self.support_select_sound_mode):
            raise NotImplementedError()

        if sound_mode not in self._codes["sound_modes"]:
            raise MediaPlayerException(f"Invalid sound mode '{sound_mode}'")

        command = self._codes["sound_modes"][sound_mode]
        await self._async_send_command(command)
