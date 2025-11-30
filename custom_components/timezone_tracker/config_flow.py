"""Config flow for Timezone Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_GPS_ENTITY,
    CONF_TIMEZONE_DATA_PATH,
    CONF_MIN_INTERVAL,
    CONF_MAX_INTERVAL,
    CONF_HYSTERESIS_COUNT,
    CONF_REGION_FILTER,
    DEFAULT_TIMEZONE_DATA_PATH,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_HYSTERESIS_COUNT,
    DEFAULT_REGION_FILTER,
    REGION_FILTERS,
)

_LOGGER = logging.getLogger(__name__)


def _get_device_trackers(hass: HomeAssistant) -> list[str]:
    """Get list of device_tracker entities with GPS attributes."""
    entities = []
    for state in hass.states.async_all("device_tracker"):
        attrs = state.attributes
        if attrs.get("latitude") or attrs.get("Latitude"):
            entities.append(state.entity_id)
    return sorted(entities)


class TimezoneTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Timezone Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate GPS entity exists
            gps_entity = user_input[CONF_GPS_ENTITY]
            state = self.hass.states.get(gps_entity)
            
            if state is None:
                errors["base"] = "entity_not_found"
            else:
                attrs = state.attributes
                if not (attrs.get("latitude") or attrs.get("Latitude")):
                    errors["base"] = "no_gps_attributes"

            if not errors:
                # Check for duplicate entries
                await self.async_set_unique_id(gps_entity)
                self._abort_if_unique_id_configured()

                region_filter = user_input.get(CONF_REGION_FILTER, DEFAULT_REGION_FILTER)

                return self.async_create_entry(
                    title=f"Timezone Tracker ({gps_entity})",
                    data={
                        CONF_GPS_ENTITY: gps_entity,
                        CONF_TIMEZONE_DATA_PATH: DEFAULT_TIMEZONE_DATA_PATH,
                        CONF_REGION_FILTER: region_filter,
                    },
                )

        # Get available device trackers
        device_trackers = _get_device_trackers(self.hass)

        if not device_trackers:
            return self.async_abort(reason="no_device_trackers")

        # Build region filter options for selector
        region_options = [
            selector.SelectOptionDict(value=key, label=label)
            for key, label in REGION_FILTERS.items()
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_GPS_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Required(
                    CONF_REGION_FILTER, default=DEFAULT_REGION_FILTER
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=region_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TimezoneTrackerOptionsFlow(config_entry)


class TimezoneTrackerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Timezone Tracker."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Check if region filter changed
            current_region = self.config_entry.data.get(CONF_REGION_FILTER, DEFAULT_REGION_FILTER)
            new_region = user_input.get(CONF_REGION_FILTER, current_region)
            
            if new_region != current_region:
                # Region changed - need to update config entry data and trigger re-download
                new_data = {**self.config_entry.data, CONF_REGION_FILTER: new_region}
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                
                # Delete existing timezone data file to force re-download
                timezone_data_path = self.config_entry.data.get(
                    CONF_TIMEZONE_DATA_PATH, DEFAULT_TIMEZONE_DATA_PATH
                )
                
                def delete_data_file():
                    import os
                    if os.path.exists(timezone_data_path):
                        os.remove(timezone_data_path)
                        return True
                    return False
                
                deleted = await self.hass.async_add_executor_job(delete_data_file)
                if deleted:
                    _LOGGER.info(f"Deleted timezone data file for re-download with new region: {new_region}")
            
            # Save options (excluding region_filter which goes in data)
            options_to_save = {
                k: v for k, v in user_input.items() 
                if k != CONF_REGION_FILTER
            }
            
            return self.async_create_entry(title="", data=options_to_save)

        # Get current region from config entry data
        current_region = self.config_entry.data.get(CONF_REGION_FILTER, DEFAULT_REGION_FILTER)

        # Build region filter options for selector
        region_options = [
            selector.SelectOptionDict(value=key, label=label)
            for key, label in REGION_FILTERS.items()
        ]

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_REGION_FILTER,
                    default=current_region,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=region_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MIN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=300,
                        step=10,
                        unit_of_measurement="seconds",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_MAX_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=300,
                        max=7200,
                        step=60,
                        unit_of_measurement="seconds",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_HYSTERESIS_COUNT,
                    default=self.config_entry.options.get(
                        CONF_HYSTERESIS_COUNT, DEFAULT_HYSTERESIS_COUNT
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=5,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
