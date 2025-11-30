"""Sensor platform for Timezone Tracker."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ATTR_EDGE_DISTANCE,
    ATTR_HEADING_DISTANCE,
    ATTR_NEAREST_TIMEZONE,
    ATTR_DETECTED_TIMEZONE,
    ATTR_PENDING_CHANGE,
    ATTR_PENDING_COUNT,
    ATTR_DISTANCE_CATEGORY,
    ATTR_SPEED_CATEGORY,
    ATTR_INTERVAL_MINUTES,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_HEADING,
    ATTR_SPEED,
)
from .coordinator import TimezoneTrackerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Timezone Tracker sensors."""
    coordinator: TimezoneTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        TimezoneBoundaryDistanceSensor(coordinator, entry),
        CurrentTimezoneSensor(coordinator, entry),
        TimezoneCheckIntervalSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class TimezoneTrackerSensorBase(SensorEntity):
    """Base class for Timezone Tracker sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TimezoneTrackerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Timezone Tracker",
            manufacturer="Custom",
            model="GPS Timezone Tracker",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TimezoneBoundaryDistanceSensor(TimezoneTrackerSensorBase):
    """Sensor for distance to timezone boundary."""

    _attr_name = "Boundary Distance"
    _attr_native_unit_of_measurement = "mi"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:map-marker-distance"

    def __init__(
        self,
        coordinator: TimezoneTrackerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_boundary_distance"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        dist = self.coordinator.data.effective_distance
        if dist == float('inf') or dist > 9999:
            return None
        return round(dist, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        data = self.coordinator.data
        attrs = {
            ATTR_LATITUDE: data.latitude,
            ATTR_LONGITUDE: data.longitude,
            ATTR_HEADING: data.heading,
            ATTR_SPEED: data.speed,
        }

        if data.edge_distance < 9999:
            attrs[ATTR_EDGE_DISTANCE] = round(data.edge_distance, 1)
        if data.heading_distance < 9999:
            attrs[ATTR_HEADING_DISTANCE] = round(data.heading_distance, 1)
        if data.nearest_other_timezone:
            attrs[ATTR_NEAREST_TIMEZONE] = data.nearest_other_timezone

        return attrs


class CurrentTimezoneSensor(TimezoneTrackerSensorBase):
    """Sensor for current timezone."""

    _attr_name = "Current Timezone"
    _attr_icon = "mdi:clock-time-four"

    def __init__(
        self,
        coordinator: TimezoneTrackerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_timezone"

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.coordinator.data.current_timezone

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        data = self.coordinator.data
        attrs = {
            ATTR_DETECTED_TIMEZONE: data.detected_timezone,
        }

        if data.effective_distance < 9999:
            attrs["distance_to_edge"] = round(data.effective_distance, 1)

        if data.pending_timezone:
            attrs[ATTR_PENDING_CHANGE] = data.pending_timezone
            attrs[ATTR_PENDING_COUNT] = data.pending_count

        return attrs


class TimezoneCheckIntervalSensor(TimezoneTrackerSensorBase):
    """Sensor for current check interval."""

    _attr_name = "Check Interval"
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:timer-refresh"

    def __init__(
        self,
        coordinator: TimezoneTrackerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_check_interval"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        return self.coordinator.data.check_interval

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            ATTR_DISTANCE_CATEGORY: self.coordinator.get_distance_category(),
            ATTR_SPEED_CATEGORY: self.coordinator.get_speed_category(),
            ATTR_INTERVAL_MINUTES: round(self.coordinator.data.check_interval / 60, 1),
        }
