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

    # Store coordinator first so it's available for services
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Try to load timezone data - if file exists locally, this is fast
    # If download is needed, do it in background to avoid setup timeout
    if os.path.exists(timezone_data_path):
        # File exists - try to load it (fast operation)
        if not await coordinator.async_load_timezone_data():
            _LOGGER.warning("Failed to load timezone data, will retry in background")
    else:
        # File doesn't exist - start background download
        _LOGGER.info("Timezone data not found, starting background download...")
        
        async def background_download():
            """Download and load timezone data in background."""
            try:
                if await coordinator.async_load_timezone_data():
                    _LOGGER.info("Background timezone data download complete")
                    # Trigger an update now that we have data
                    await coordinator.async_force_update()
                else:
                    _LOGGER.error("Background timezone data download failed")
            except Exception as e:
                _LOGGER.error(f"Background download error: {e}")
        
        hass.async_create_task(background_download())

    # Start the coordinator (will wait for data if not loaded yet)
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
