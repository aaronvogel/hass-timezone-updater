"""
Timezone Tracker Integration for Home Assistant.

Tracks timezone boundaries locally using OpenStreetMap polygon data and
automatically updates Home Assistant's timezone when you cross a boundary.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_GPS_ENTITY,
    CONF_MIN_INTERVAL,
    CONF_MAX_INTERVAL,
    CONF_HYSTERESIS_COUNT,
    CONF_REGION_FILTER,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_HYSTERESIS_COUNT,
    DEFAULT_REGION_FILTER,
    STORAGE_DIR,
    STORAGE_FILENAME,
)
from .coordinator import TimezoneTrackerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def get_storage_path(hass: HomeAssistant) -> str:
    """Get the path for storing timezone data in .storage directory."""
    return hass.config.path(".storage", STORAGE_DIR, STORAGE_FILENAME)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Timezone Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Get configuration
    gps_entity = entry.data[CONF_GPS_ENTITY]
    timezone_data_path = get_storage_path(hass)
    region_filter = entry.data.get(CONF_REGION_FILTER, DEFAULT_REGION_FILTER)
    min_interval = entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
    max_interval = entry.options.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL)
    hysteresis_count = entry.options.get(CONF_HYSTERESIS_COUNT, DEFAULT_HYSTERESIS_COUNT)

    # Create coordinator
    coordinator = TimezoneTrackerCoordinator(
        hass,
        gps_entity=gps_entity,
        timezone_data_path=timezone_data_path,
        region_filter=region_filter,
        min_interval=min_interval,
        max_interval=max_interval,
        hysteresis_count=hysteresis_count,
    )

    # Load timezone data
    if not await coordinator.async_load_timezone_data():
        _LOGGER.error("Failed to load timezone boundary data")
        return False

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start the coordinator
    await coordinator.async_start()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_force_update(call: ServiceCall) -> None:
        """Handle force update service call."""
        await coordinator.async_force_update()

    async def handle_reload_data(call: ServiceCall) -> None:
        """Handle reload data service call."""
        await coordinator.async_load_timezone_data()

    async def handle_download_data(call: ServiceCall) -> None:
        """Handle download data service call - forces re-download."""
        # Delete existing file
        if os.path.exists(coordinator.timezone_data_path):
            await hass.async_add_executor_job(os.remove, coordinator.timezone_data_path)
            _LOGGER.info(f"Deleted existing timezone data file")
        # Re-download and load
        await coordinator.async_load_timezone_data()

    hass.services.async_register(DOMAIN, "force_update", handle_force_update)
    hass.services.async_register(DOMAIN, "reload_data", handle_reload_data)
    hass.services.async_register(DOMAIN, "download_data", handle_download_data)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Stop coordinator
    coordinator: TimezoneTrackerCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_stop()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
