import logging
import traceback
import datetime
import os
import sqlite3
from collections import OrderedDict
from sensor_map import *


class ThermostatDatabase:
    def __init__(self):
        self._logger = logging.getLogger("thermostat")

        self._conn = None
        self._cur = None

        self._db_file_directory_name = 'db'
        self._db_file_name = 'thermostat'
        self._db_file_ext = '.db'
        self._db_file_path = os.path.join(self._db_file_directory_name, self._db_file_name + self._db_file_ext)

    def open(self):
        try:
            os.makedirs(self._db_file_directory_name)
        except FileExistsError:
            pass

        self._conn = sqlite3.connect(self._db_file_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.commit()
        self._cur = self._conn.cursor()

    def _execute_sql_command(self, command):
        try:
            self._cur.execute(command)
        except sqlite3.OperationalError as e:
            self._logger.info("## {} Exception occured in ThermostatDatabase: {}".format(datetime.datetime.now().strftime('%H:%M:%S'), str(e)))
            self._logger.info("SQL command: {}".format(command))
            self._logger.info(traceback.format_exc())
            raise e

    def _create_table_if_not_exists(self, room_name):
        self._cur.execute('''CREATE TABLE IF NOT EXISTS {room_name:}(date                   TEXT PRIMARY KEY NOT NULL, \
                                                                     current_temperature    REAL, \
                                                                     current_humidity       REAL, \
                                                                     current_pipe_in        REAL, \
                                                                     current_pipe_out       REAL, \
                                                                     target_temperature     REAL, \
                                                                     boiler_state           INTEGER \
                                                                     data_missing           INTEGER NOT NULL)'''.format(room_name=room_name))

    def insert_sensor_data(self, room_name, t, current_temperature, current_humidity, current_pipe_in, current_pipe_out, target_temperature, boiler_state, data_missing):
        command = '''INSERT INTO {room_name:} VALUES ('{time:}', \
                                                      {current_temperature:}, \
                                                      {current_humidity:}, \
                                                      {current_pipe_in}, \
                                                      {current_pipe_out}, \
                                                      {target_temperature}, \
                                                      {boiler_state}, 
                                                      {data_missing})'''.format(room_name=room_name,
                                                                                time=t.strftime('%Y-%m-%d %H:%M:%S'),
                                                                                current_temperature=current_temperature if current_temperature is not None else "NULL",
                                                                                current_humidity=current_humidity if current_humidity is not None else "NULL",
                                                                                current_pipe_in=current_pipe_in if current_pipe_in is not None else "NULL",
                                                                                current_pipe_out=current_pipe_out if current_pipe_out is not None else "NULL",
                                                                                target_temperature=target_temperature if target_temperature is not None else "NULL",
                                                                                boiler_state=boiler_state if boiler_state is not None else "NULL",
                                                                                data_missing=data_missing)
        try:
            self._execute_sql_command(command)
        except sqlite3.OperationalError as e:
            self._create_table_if_not_exists(room_name)
            self._execute_sql_command(command)

    def rollover(self):
        self.close()

        src = self._db_file_path
        dst = os.path.join(self._db_file_directory_name, '{file_name:}_{date:}{file_ext:}'.format(file_name=self._db_file_name, date=datetime.datetime.now().strftime('%Y-%m-%d'), file_ext=self._db_file_ext))
        os.rename(src, dst)

        self.open()

    def close(self):
        self._conn.commit()
        self._conn.close()


class ThermostatDatabaseStream:
    def __init__(self):
        self._last_sensor_data_sync_time = {sensor_name: None for sensor_name in SENSOR_NAMES}
        self._conn = None
        self._cur = None

        self._db_file_directory_name = 'db'
        self._db_file_name = 'thermostat'
        self._db_file_ext = '.db'
        self._db_file_path = os.path.join(self._db_file_directory_name, self._db_file_name + self._db_file_ext)

    def _build_db_file_paths(self, since):
        today0 = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        since0 = since.replace(hour=0, minute=0, second=0, microsecond=0)

        db_file_names = []
        while since0 < today0:
            db_file_name = os.path.join(self._db_file_directory_name, '{file_name:}_{date:}{file_ext:}'.format(file_name=self._db_file_name, date=since0.strftime('%Y-%m-%d'), file_ext=self._db_file_ext))
            db_file_names.append(db_file_name)
            since0 += datetime.timedelta(days=1)

        db_file_names.append(self._db_file_path)

        return db_file_names

    def get_data(self):
        sensor_data_collection = {}
        for sensor_name in SENSOR_NAMES:
            sensor_data, self._last_sensor_data_sync_time[sensor_name] = self._read_sensor_data(sensor_name, self._last_sensor_data_sync_time[sensor_name])
            sensor_data_collection[sensor_name] = sensor_data

        return sensor_data_collection

    def get_initial_data(self, last_db_sync_times):
        if isinstance(last_db_sync_times, dict):
            since = min(last_db_sync_times.values())
        else:
            since = last_db_sync_times
            last_db_sync_times = {sensor_name: since for sensor_name in SENSOR_NAMES}

        db_file_names = self._build_db_file_paths(since)

        today_db_file_name = os.path.join(self._db_file_directory_name, '{file_name:}{file_ext:}'.format(file_name=self._db_file_name, file_ext=self._db_file_ext))

        sensor_data_collection = {sensor_name: OrderedDict() for sensor_name in SENSOR_NAMES}

        for db_file_name in db_file_names:
            if os.path.exists(db_file_name):
                self._conn = sqlite3.connect('file:{}?mode=ro'.format(db_file_name), uri=True)
                self._cur = self._conn.cursor()

                for sensor_name in SENSOR_NAMES:
                    sensor_data, self._last_sensor_data_sync_time[sensor_name] = self._read_sensor_data(sensor_name, last_db_sync_times[sensor_name])
                    sensor_data_collection[sensor_name].update(sensor_data)

                if db_file_name != today_db_file_name:
                    self._cur.close()
                    self._conn.close()

        return sensor_data_collection

    def _read_sensor_data(self, sensor_name, since):
        command = '''SELECT * FROM {sensor_name:} WHERE date > strftime('%Y-%m-%d %H:%M:%S', '{since:}') ORDER BY date;'''.format(sensor_name=sensor_name, since=since.strftime('%Y-%m-%d %H:%M:%S'))

        t = since
        sensor_data = OrderedDict()
        for t, temperature, humidity in self._cur.execute(command):
            t = datetime.datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
            if t > since:
                sensor_data[t] = (temperature, humidity)

        return sensor_data, t

    def close_database(self):
        self.quit()

        last_sensor_data_sync_time = self._last_sensor_data_sync_time

        self._last_sensor_data_sync_time = {sensor_name: None for sensor_name in SENSOR_NAMES}

        return last_sensor_data_sync_time

    def quit(self):
        if self._cur:
            self._cur.close()
            self._cur = None

        if self._conn:
            self._conn.close()
            self._conn = None

