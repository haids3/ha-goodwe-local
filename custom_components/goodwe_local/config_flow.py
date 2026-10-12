"""Config flow to configure Goodwe inverters using their local API."""

import logging
from typing import Any, override

from goodwe import Inverter, InverterError, connect
from goodwe.const import GOODWE_TCP_PORT, GOODWE_UDP_PORT
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_ALLOW_CONTROL, CONF_MODEL_FAMILY, DEFAULT_NAME, DOMAIN

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ALLOW_CONTROL, default=False): bool,
    }
)

_LOGGER = logging.getLogger(__name__)

# TXT record of the dongle's _goodwe._tcp advertisement.
ZEROCONF_MODBUS_PORT = "inverter-modbustcp-port"


class GoodweFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Goodwe config flow."""

    VERSION = 2

    _discovered_host: str
    _discovered_port: int
    _discovered_inverter: Inverter

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GoodweOptionsFlow:
        """Get the options flow for this handler."""
        return GoodweOptionsFlow()

    async def async_handle_successful_connection(
        self,
        inverter: Inverter,
        host: str,
        port: int,
    ) -> ConfigFlowResult:
        """Handle a successful connection storing it's values on the entry data."""
        await self.async_set_unique_id(inverter.serial_number)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=DEFAULT_NAME,
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_MODEL_FAMILY: type(inverter).__name__,
            },
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                inverter, port = await self.async_detect_inverter_port(host=host)
            except InverterError:
                errors[CONF_HOST] = "connection_error"
            else:
                return await self.async_handle_successful_connection(
                    inverter, host, port
                )
        return self.async_show_form(
            step_id="user", data_schema=CONFIG_SCHEMA, errors=errors
        )

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a GoodWe dongle discovered via zeroconf."""
        host = discovery_info.host
        self._async_abort_entries_match({CONF_HOST: host})

        # The advertisement names the dongle, not the inverter, so connect to
        # learn the inverter serial number the entries are keyed by.
        try:
            port = int(discovery_info.properties.get(ZEROCONF_MODBUS_PORT, ""))
        except ValueError:
            port = GOODWE_TCP_PORT
        try:
            inverter, port = await self._async_connect_discovered(host, port)
        except InverterError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(inverter.serial_number)
        # Keep the configured port: the inverter may answer on both.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self._discovered_port = port
        self._discovered_inverter = inverter
        self.context["title_placeholders"] = {"name": inverter.serial_number}
        return await self.async_step_discovery_confirm()

    @staticmethod
    async def _async_connect_discovered(host: str, port: int) -> tuple[Inverter, int]:
        """Connect on the advertised Modbus TCP port, else over UDP."""
        try:
            return await connect(host=host, port=port, retries=3), port
        except InverterError:
            return await connect(host=host, port=GOODWE_UDP_PORT, retries=3), (
                GOODWE_UDP_PORT
            )

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setting up a discovered inverter."""
        if user_input is not None:
            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_HOST: self._discovered_host,
                    CONF_PORT: self._discovered_port,
                    CONF_MODEL_FAMILY: type(self._discovered_inverter).__name__,
                },
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "serial_number": self._discovered_inverter.serial_number,
                "host": self._discovered_host,
            },
        )

    @staticmethod
    async def async_detect_inverter_port(
        host: str,
    ) -> tuple[Inverter, int]:
        """Detects the port of the Inverter."""
        port = GOODWE_UDP_PORT
        try:
            inverter = await connect(host=host, port=port, retries=3)
        except InverterError:
            port = GOODWE_TCP_PORT
            inverter = await connect(host=host, port=port, retries=3)
        return inverter, port


class GoodweOptionsFlow(OptionsFlow):
    """Handle GoodWe options."""

    _options: dict[str, Any]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            if user_input[CONF_ALLOW_CONTROL] and not self.config_entry.options.get(
                CONF_ALLOW_CONTROL, False
            ):
                self._options = user_input
                return await self.async_step_confirm_control()
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )

    async def async_step_confirm_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Warn before allowing controls."""
        if user_input is not None:
            return self.async_create_entry(data=self._options)
        return self.async_show_form(step_id="confirm_control")
