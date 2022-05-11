"""Weather component."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from homeassistant.components.weather import ATTR_FORECAST, WeatherEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SPEED_METERS_PER_SECOND, TEMP_CELSIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_flow import get_value
from .const import (
    ATTR_API_CONDITION,
    ATTR_API_HUMIDITY,
    ATTR_API_IMAGE,
    ATTR_API_PRESSURE,
    ATTR_API_TEMPERATURE,
    ATTR_API_WIND_BEARING,
    ATTR_API_WIND_SPEED,
    ATTRIBUTION,
    CONF_IMAGE_SOURCE,
    DOMAIN,
    ENTRY_NAME,
    UPDATER,
    get_image,
)
from .updater import WeatherUpdater

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up weather "Yandex.Weather" weather entry."""
    domain_data = hass.data[DOMAIN][config_entry.entry_id]
    name = domain_data[ENTRY_NAME]
    updater = domain_data[UPDATER]

    async_add_entities([YandexWeather(name, config_entry, updater, hass)], False)


class YandexWeather(WeatherEntity, CoordinatorEntity, RestoreEntity):
    """Yandex.Weather entry."""

    _attr_attribution = ATTRIBUTION
    _attr_wind_speed_unit = SPEED_METERS_PER_SECOND
    _attr_pressure_unit = None
    _attr_temperature_unit = TEMP_CELSIUS
    coordinator: WeatherUpdater

    def __init__(
        self,
        name,
        config_entry: ConfigEntry,
        updater: WeatherUpdater,
        hass: HomeAssistant,
    ):
        """Initialize entry."""
        WeatherEntity.__init__(self)
        CoordinatorEntity.__init__(self, coordinator=updater)
        RestoreEntity.__init__(self)

        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = config_entry.unique_id
        self._attr_device_info = self.coordinator.device_info
        self._image_source = get_value(config_entry, CONF_IMAGE_SOURCE, "Yandex")

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await RestoreEntity.async_added_to_hass(self)
        await CoordinatorEntity.async_added_to_hass(self)

        state = await self.async_get_last_state()
        if not state:
            _LOGGER.debug("Have no state for restore!")
            await self.coordinator.async_config_entry_first_refresh()
            return

        _LOGGER.debug(f"state for restore: {state}")
        self._attr_temperature = state.attributes.get("temperature")
        self._attr_condition = state.state
        self._attr_pressure = state.attributes.get("pressure")
        self._attr_humidity = state.attributes.get("humidity")
        self._attr_wind_speed = state.attributes.get("wind_speed")
        self._attr_wind_bearing = state.attributes.get("wind_bearing")
        self._attr_entity_picture = state.attributes.get("entity_picture")
        self._attr_forecast = state.attributes.get(ATTR_FORECAST)
        self.async_write_ha_state()

        # last_updated is last call of self.async_write_ha_state(), not a real last update
        since_last_update = datetime.now(timezone.utc) - state.last_updated.replace(
            tzinfo=timezone.utc
        )
        _LOGGER.debug(
            f"Time since last update: {since_last_update} ({state.last_updated}), "
            f"update interval is {self.coordinator.update_interval}"
        )
        if since_last_update > self.coordinator.update_interval:
            await self.coordinator.async_config_entry_first_refresh()
        else:
            self.coordinator.schedule_refresh(
                offset=self.coordinator.update_interval - since_last_update
            )

    def _handle_coordinator_update(self) -> None:
        self._attr_temperature = self.coordinator.data.get(ATTR_API_TEMPERATURE)
        self._attr_condition = self.coordinator.data.get(ATTR_API_CONDITION)
        self._attr_pressure = self.coordinator.data.get(ATTR_API_PRESSURE)
        self._attr_humidity = self.coordinator.data.get(ATTR_API_HUMIDITY)
        self._attr_wind_speed = self.coordinator.data.get(ATTR_API_WIND_SPEED)
        self._attr_wind_bearing = self.coordinator.data.get(ATTR_API_WIND_BEARING)
        self._attr_entity_picture = get_image(
            image_source=self._image_source,
            condition=self.coordinator.data.get(ATTR_API_CONDITION),
            is_day=self.coordinator.data.get("daytime") == "d",
            image=self.coordinator.data.get(ATTR_API_IMAGE),
        )
        self._attr_forecast = self.coordinator.data.get(ATTR_FORECAST)
        self.async_write_ha_state()
