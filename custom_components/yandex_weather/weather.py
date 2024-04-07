"""Weather component."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from homeassistant.components.weather import (
    ATTR_WEATHER_PRECIPITATION_UNIT,
    ATTR_WEATHER_PRESSURE_UNIT,
    ATTR_WEATHER_TEMPERATURE_UNIT,
    ATTR_WEATHER_WIND_SPEED_UNIT,
    UNIT_CONVERSIONS,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_UNAVAILABLE,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_flow import get_value
from .const import (
    ATTR_API_CONDITION,
    ATTR_API_FEELS_LIKE_TEMPERATURE,
    ATTR_API_FORECAST_ICONS,
    ATTR_API_HUMIDITY,
    ATTR_API_IMAGE,
    ATTR_API_ORIGINAL_CONDITION,
    ATTR_API_PRESSURE,
    ATTR_API_TEMP_WATER,
    ATTR_API_TEMPERATURE,
    ATTR_API_WEATHER_TIME,
    ATTR_API_WIND_BEARING,
    ATTR_API_WIND_GUST,
    ATTR_API_WIND_SPEED,
    ATTR_API_YA_CONDITION,
    ATTR_FORECAST_DATA,
    ATTRIBUTION,
    CONF_IMAGE_SOURCE,
    DOMAIN,
    ENTRY_NAME,
    UPDATER,
    get_image,
)
from .device_trigger import TRIGGERS
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
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _twice_daily_forecast: list[Forecast] | None
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
        self._attr_condition = None
        self._attr_unique_id = config_entry.unique_id
        self._attr_device_info = self.coordinator.device_info
        self._attr_supported_features = WeatherEntityFeature.FORECAST_TWICE_DAILY
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

        if state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            await self.coordinator.async_config_entry_first_refresh()
        else:
            _LOGGER.debug(f"state for restore: {state}")
            self._attr_available = True
            self._attr_condition = state.state
            for attribute, converter in [
                ("temperature", UNIT_CONVERSIONS[ATTR_WEATHER_TEMPERATURE_UNIT]),
                ("pressure", UNIT_CONVERSIONS[ATTR_WEATHER_PRESSURE_UNIT]),
                ("wind_speed", UNIT_CONVERSIONS[ATTR_WEATHER_WIND_SPEED_UNIT]),
            ]:
                try:
                    setattr(
                        self,
                        f"_attr_native_{attribute}",
                        converter(
                            state.attributes.get(attribute),
                            state.attributes.get(
                                f"_{attribute}_unit",
                                getattr(self, f"_attr_native_{attribute}_unit"),
                            ),
                            getattr(self, f"_attr_native_{attribute}_unit"),
                        ),
                    )
                except TypeError:
                    pass

            self._attr_humidity = state.attributes.get("humidity")
            self._attr_wind_bearing = state.attributes.get("wind_bearing")
            self._attr_entity_picture = state.attributes.get("entity_picture")
            self._twice_daily_forecast = state.attributes.get(ATTR_FORECAST_DATA, [])
            for f in self._twice_daily_forecast:
                for attribute, converter in [
                    ("temperature", UNIT_CONVERSIONS[ATTR_WEATHER_TEMPERATURE_UNIT]),
                    ("pressure", UNIT_CONVERSIONS[ATTR_WEATHER_PRESSURE_UNIT]),
                    ("wind_speed", UNIT_CONVERSIONS[ATTR_WEATHER_WIND_SPEED_UNIT]),
                    (
                        "precipitation",
                        UNIT_CONVERSIONS[ATTR_WEATHER_PRECIPITATION_UNIT],
                    ),
                ]:
                    try:
                        f[attribute] = converter(
                            f.get(attribute),
                            getattr(
                                self,
                                f"_{attribute}_unit",
                                getattr(self, f"_attr_native_{attribute}_unit"),
                            ),
                            getattr(self, f"_attr_native_{attribute}_unit"),
                        )
                    except TypeError:
                        pass

            self._attr_extra_state_attributes = {}
            for attribute in [
                "feels_like",
                "wind_gust",
                "yandex_condition",
                "temp_water",
                "forecast_icons",
            ]:
                value = state.attributes.get(attribute)
                if value is not None:
                    self._attr_extra_state_attributes[attribute] = value

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
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._attr_available = True
        self.update_condition_and_fire_event(
            new_condition=self.coordinator.data.get(ATTR_API_CONDITION)
        )
        self._attr_entity_picture = get_image(
            image_source=self._image_source,
            condition=self.coordinator.data.get(ATTR_API_ORIGINAL_CONDITION),
            is_day=self.coordinator.data.get("daytime") == "d",
            image=self.coordinator.data.get(ATTR_API_IMAGE),
        )
        self._twice_daily_forecast = self.coordinator.data.get(ATTR_FORECAST_DATA, [])
        self._attr_humidity = self.coordinator.data.get(ATTR_API_HUMIDITY)
        self._attr_native_pressure = self.coordinator.data.get(ATTR_API_PRESSURE)
        self._attr_native_temperature = self.coordinator.data.get(ATTR_API_TEMPERATURE)
        self._attr_native_wind_speed = self.coordinator.data.get(ATTR_API_WIND_SPEED)
        self._attr_wind_bearing = self.coordinator.data.get(ATTR_API_WIND_BEARING)
        self._attr_extra_state_attributes = {
            "feels_like": self.coordinator.data.get(ATTR_API_FEELS_LIKE_TEMPERATURE),
            "wind_gust": self.coordinator.data.get(ATTR_API_WIND_GUST),
            "yandex_condition": self.coordinator.data.get(ATTR_API_YA_CONDITION),
            "forecast_icons": self.coordinator.data.get(ATTR_API_FORECAST_ICONS),
            ATTR_FORECAST_DATA: self.__forecast_twice_daily(),
        }
        try:
            self._attr_extra_state_attributes["temp_water"] = self.coordinator.data.get(
                ATTR_API_TEMP_WATER
            )
        except KeyError:
            self.coordinator.logger.debug("data have no temp_water. Skipping.")

        self.async_write_ha_state()

    def update_condition_and_fire_event(self, new_condition: str):
        """Set new condition and fire event on change."""
        if (
            new_condition != self._attr_condition
            and self.hass is not None
            and new_condition in TRIGGERS
        ):
            self.hass.bus.async_fire(
                DOMAIN + "_event",
                {
                    "device_id": self.coordinator.device_id,
                    "type": new_condition,
                },
            )

        self._attr_condition = new_condition

    def __forecast_twice_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units."""
        _LOGGER.debug(f"async_forecast_twice_daily: {self._twice_daily_forecast=}")
        # we must return at least three elements in forecast
        # https://github.com/home-assistant/frontend/blob/dev/src/data/weather.ts#L548
        if len(result := self._twice_daily_forecast) < 3:
            _LOGGER.debug(
                "Have not enough forecast data. Adding current weather to forecast..."
            )
            result.insert(
                0,
                Forecast(
                    datetime=self.coordinator.data.get(ATTR_API_WEATHER_TIME),
                    wind_bearing=self.wind_bearing,
                    native_temperature=self.native_temperature,
                    temperatrue=self.native_temperature,
                    native_templow=self.native_temperature,
                    templow=self.native_temperature,
                    native_pressure=self.native_pressure,
                    native_wind_speed=self.native_wind_speed,
                    condition=self.condition,
                    # is_daytime=self.is_daytime,
                ),
            )
        return result

    async def async_forecast_twice_daily(self) -> list[Forecast] | None:
        return self.__forecast_twice_daily()
