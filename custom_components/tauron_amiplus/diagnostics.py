from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .connector import TauronAmiplusConnector
from .const import (CONF_METER_ID, CONF_SHOW_GENERATION, CONF_TARIFF)


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    return await hass.async_add_executor_job(get_config_entry_diagnostics, entry)


def get_config_entry_diagnostics(entry: ConfigEntry) -> dict[str, Any]:
    user = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    meter_id = entry.data[CONF_METER_ID]
    show_generation_sensors = entry.data[CONF_SHOW_GENERATION]
    tariff = entry.data[CONF_TARIFF]

    connector = TauronAmiplusConnector(user, password, meter_id)
    raw_data = connector.get_raw_data()

    return {
        "tariff": tariff,
        "show_generation_sensors": show_generation_sensors,
        "raw_data_tariff": raw_data.tariff,
        "raw_data_consumption": {
            "json_reading": raw_data.consumption.json_reading,
            "json_daily": raw_data.consumption.json_daily,
            "daily_date": raw_data.consumption.daily_date,
            "json_monthly": raw_data.consumption.json_monthly,
            "json_yearly": raw_data.consumption.json_yearly,
        },
        "raw_data_generation": {
            "json_reading": raw_data.generation.json_reading,
            "json_daily": raw_data.generation.json_daily,
            "daily_date": raw_data.generation.daily_date,
            "json_monthly": raw_data.generation.json_monthly,
            "json_yearly": raw_data.generation.json_yearly,
        },
        "raw_data_balanced": {
            "balance_monthly": raw_data.balance_monthly
        }
    }
