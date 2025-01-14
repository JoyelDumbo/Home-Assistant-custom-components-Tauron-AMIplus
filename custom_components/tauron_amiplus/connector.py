"""Update coordinator for TAURON sensors."""
import datetime
import logging
import ssl
from typing import Optional

import requests
from requests import adapters
from urllib3 import poolmanager

from .const import (CONST_DATE_FORMAT, CONST_MAX_LOOKUP_RANGE, CONST_REQUEST_HEADERS, CONST_URL_ENERGY, CONST_URL_LOGIN,
                    CONST_URL_READINGS, CONST_URL_SELECT_METER, CONST_URL_SERVICE)

_LOGGER = logging.getLogger(__name__)


# to fix the SSLError
class TLSAdapter(adapters.HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        """Create and initialize the urllib3 PoolManager."""
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.check_hostname = False
        self.poolmanager = poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_version=ssl.PROTOCOL_TLS,
            ssl_context=ctx,
        )


class TauronAmiplusRawData:
    def __init__(self):
        self.tariff = None
        self.consumption: Optional[TauronAmiplusDataSet] = None
        self.generation: Optional[TauronAmiplusDataSet] = None

    def data_unavailable(self):
        return self.consumption is None or self.generation is None

    @property
    def balance_daily(self):
        if self.data_unavailable() or self.consumption.json_daily is None or self.generation.json_daily is None:
            return None
        return self.consumption.json_daily, self.generation.json_daily

    @property
    def balance_monthly(self):
        if (self.data_unavailable() or self.consumption.json_month_hourly is None or
                self.generation.json_month_hourly is None):
            return None
        return self.consumption.json_month_hourly, self.generation.json_month_hourly

    @property
    def balance_last_12_months_hourly(self):
        if (self.data_unavailable() or
                self.consumption.json_last_12_months_hourly is None or
                self.generation.json_last_12_months_hourly is None):
            return None
        return self.consumption.json_last_12_months_hourly, self.generation.json_last_12_months_hourly

    @property
    def balance_configurable_hourly(self):
        if (self.data_unavailable() or
                self.consumption.json_configurable_hourly is None or
                self.generation.json_configurable_hourly is None):
            return None
        return self.consumption.json_configurable_hourly, self.generation.json_configurable_hourly


class TauronAmiplusDataSet:
    def __init__(self):
        self.json_reading = None
        self.json_daily = None
        self.daily_date = None
        self.json_monthly = None
        self.json_yearly = None
        self.json_month_hourly = None
        self.json_last_30_days_hourly = None
        self.json_last_12_months_hourly = None
        self.json_configurable_hourly = None


class TauronAmiplusConnector:

    def __init__(self, username, password, meter_id, show_generation=False, show_12_months=False, show_balanced=False,
                 show_configurable=False, show_configurable_date=None):
        self.username = username
        self.password = password
        self.meter_id = meter_id
        self.show_generation = show_generation
        self.show_12_months = show_12_months
        self.show_balanced = show_balanced
        self.show_configurable = show_configurable
        self.show_configurable_date = show_configurable_date
        self.session = None

    def get_raw_data(self) -> TauronAmiplusRawData:
        data = TauronAmiplusRawData()
        self.login()

        data.consumption = self.get_data_set(generation=False)
        if self.show_generation or self.show_balanced:
            data.generation = self.get_data_set(generation=True)
        else:
            data.generation = TauronAmiplusDataSet()
        if data.consumption.json_yearly is not None:
            data.tariff = data.consumption.json_yearly["data"]["tariff"]
        return data

    def get_data_set(self, generation) -> TauronAmiplusDataSet:
        dataset = TauronAmiplusDataSet()
        dataset.json_reading = self.get_reading(generation)
        dataset.json_daily, dataset.daily_date = self.get_values_daily(generation)
        dataset.json_monthly = self.get_values_monthly(generation)
        dataset.json_yearly = self.get_values_yearly(generation)
        dataset.json_month_hourly = self.get_values_month_hourly(generation)
        dataset.json_last_30_days_hourly = self.get_values_last_30_days_hourly(generation)
        if self.show_12_months:
            dataset.json_last_12_months_hourly = self.get_values_12_months_hourly(generation)
        if self.show_configurable:
            start = self.show_configurable_date
            end = datetime.datetime.now()
            dataset.json_configurable_hourly = self.get_raw_values_daily_for_range(start, end, generation)

        return dataset

    def login(self):
        payload_login = {
            "username": self.username,
            "password": self.password,
            "service": CONST_URL_SERVICE,
        }
        session = requests.session()
        session.mount("https://", TLSAdapter())
        session.request(
            "POST",
            CONST_URL_LOGIN,
            data=payload_login,
            headers=CONST_REQUEST_HEADERS,
        )
        session.request(
            "POST",
            CONST_URL_LOGIN,
            data=payload_login,
            headers=CONST_REQUEST_HEADERS,
        )
        payload_select_meter = {"site[client]": self.meter_id}
        session.request("POST", CONST_URL_SELECT_METER, data=payload_select_meter, headers=CONST_REQUEST_HEADERS)
        self.session = session

    def calculate_configuration(self, days_before=2, throw_on_empty=True):
        json_data, _ = self.get_raw_values_daily(days_before, generation=False)
        if json_data is None:
            if throw_on_empty:
                raise Exception("Failed to login")
            else:
                return None
        tariff = json_data["data"]["tariff"]
        return tariff

    def get_values_yearly(self, generation):
        now = datetime.datetime.now()
        first_day_of_year = now.replace(day=1, month=1)
        last_day_of_year = now.replace(day=31, month=12)
        payload = {
            "from": TauronAmiplusConnector.format_date(first_day_of_year),
            "to": TauronAmiplusConnector.format_date(last_day_of_year),
            "profile": "year",
            "type": "oze" if generation else "consum",
        }
        return self.get_chart_values(payload)

    def get_values_monthly(self, generation):
        now = datetime.datetime.now()
        month = now.month
        first_day_of_month = now.replace(day=1)
        last_day_of_month = first_day_of_month.replace(month=month % 12 + 1) - datetime.timedelta(days=1)

        payload = {
            "from": TauronAmiplusConnector.format_date(first_day_of_month),
            "to": TauronAmiplusConnector.format_date(last_day_of_month),
            "profile": "month",
            "type": "oze" if generation else "consum",
        }
        return self.get_chart_values(payload)

    def get_values_daily(self, generation):
        offset = 1
        data = None
        day = None
        while offset <= CONST_MAX_LOOKUP_RANGE and (data is None or len(data["data"]["allData"]) < 24):
            data, day = self.get_raw_values_daily(offset, generation)
            offset += 1
        return data, day

    def get_raw_values_daily(self, days_before, generation):
        day = datetime.datetime.now() - datetime.timedelta(days_before)
        return self.get_raw_values_daily_for_range(day, day, generation), TauronAmiplusConnector.format_date(day)

    def get_values_month_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now.replace(day=1)
        return self.get_raw_values_daily_for_range(start_day, now, generation)

    def get_values_last_30_days_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now - datetime.timedelta(days=30)
        return self.get_raw_values_daily_for_range(start_day, now, generation)

    def get_values_12_months_hourly(self, generation):
        now = datetime.datetime.now()
        start_day = now.replace(year=now.year - 1)
        return self.get_raw_values_daily_for_range(start_day, now, generation)

    def get_raw_values_daily_for_range(self, day_from, day_to, generation):
        payload = {
            "from": TauronAmiplusConnector.format_date(day_from),
            "to": TauronAmiplusConnector.format_date(day_to),
            "profile": "full time",
            "type": "oze" if generation else "consum",
        }
        return self.get_chart_values(payload)

    def get_reading(self, generation):
        date_to = datetime.datetime.now()
        date_from = (date_to - datetime.timedelta(CONST_MAX_LOOKUP_RANGE))

        payload = {
            "from": TauronAmiplusConnector.format_date(date_from),
            "to": TauronAmiplusConnector.format_date(date_to),
            "type": "energia-oddana" if generation else "energia-pobrana"
        }
        return self.execute_post(CONST_URL_READINGS, payload)

    def get_chart_values(self, payload):
        return self.execute_post(CONST_URL_ENERGY, payload)

    def execute_post(self, url, payload):
        response = self.session.request(
            "POST",
            url,
            data=payload,
            headers=CONST_REQUEST_HEADERS,
        )
        if response.status_code == 200 and response.text.startswith('{"success":true'):
            json_data = response.json()
            return json_data
        return None

    @staticmethod
    def format_date(date):
        return date.strftime(CONST_DATE_FORMAT)

    @staticmethod
    def calculate_tariff(username, password, meter_id):
        connector = TauronAmiplusConnector(username, password, meter_id)
        connector.login()
        config = connector.calculate_configuration()
        if config is not None:
            return config
        raise Exception("Failed to login")
