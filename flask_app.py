from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states, rotate_rotary_encoder
import threading
import sys
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR
import logging
from logging.handlers import TimedRotatingFileHandler
from database import ThermostatDatabase
import os
import signal
import datetime
import time
import requests
import concurrent.futures
from pprint import pprint, pformat


THERMOSTAT_OFF_TEMPERATURE = 5.0
THERMOSTAT_ON_TEMPERATURE = 25.0


PIPES_BOILER    = 'PIPES_BOILER'

ROOM_LIVING     = 'ROOM_LIVING'
ROOM_BED        = 'ROOM_BED'
ROOM_COMPUTER   = 'ROOM_COMPUTER'
ROOM_HANS       = 'ROOM_HANS'
ROOMS = (ROOM_LIVING, ROOM_BED, ROOM_COMPUTER, ROOM_HANS)   # The order follows honeywell_dt200 controler room order. It should not be changed!!


STATE_DTIME = "STATE_DTIME"
STATE_TEMPERATURE = "STATE_TEMPERATURE"
STATE_HUMIDITY = "STATE_HUMIDITY"
STATE_PIPE_IN = "STATE_PIPE_IN"
STATE_PIPE_OUT = "STATE_PIPE_OUT"
STATE_TARGET = "STATE_TARGET"
STATE_BOILER = "STATE_BOILER"
STATE_DATA_MISSING_COUNT = "STATE_DATA_MISSING_COUNT"


# The order has a dependency to index.html
default_room_state = {
    STATE_DTIME:                datetime.datetime(1970, 1, 1, 9, 0),
    STATE_TEMPERATURE:          0.0,
    STATE_HUMIDITY:             0.0,
    STATE_PIPE_IN:              0.0,
    STATE_PIPE_OUT:             0.0,
    STATE_TARGET:               THERMOSTAT_OFF_TEMPERATURE,
    STATE_BOILER:               False,
    STATE_DATA_MISSING_COUNT:   0
}


thermostat_states = {
    ROOM_LIVING:    default_room_state.copy(),
    ROOM_BED:       default_room_state.copy(),
    ROOM_COMPUTER:  default_room_state.copy(),
    ROOM_HANS:      default_room_state.copy(),
}


temperature_servers = {
    PIPES_BOILER:   "http://192.168.50.32/temperature",
    ROOM_LIVING:    "http://192.168.50.34/temperature",
    ROOM_BED:       "http://192.168.50.35/temperature",
    ROOM_HANS:      "http://192.168.50.36/temperature",
    ROOM_COMPUTER:  "http://192.168.50.37/temperature"
}


OUT_PIPE_NAME = {
    PIPES_BOILER:   'PIPE_IN_MAIN',
    ROOM_LIVING:    'LIVINGROOM1H',    # or LIVINGROOM2H
    ROOM_BED:       'BEDROOM1',
    ROOM_COMPUTER:  'BEDROOM2',
    ROOM_HANS:      'BEDROOM3'
}


log = None
scheduler = None
app = Flask(__name__)
lock = threading.Lock()
thermostat_db = None


"""
TARGET      = 0
CURRENT     = 1
OUT_PIPE    = 2
BOILER      = 3
LAST_TIME_BOILER_ONOFF = 4

last_temperatures_and_humidities = None

states = {
    # ROOM          TARGET              CURRENT     OUT PIPE    BOILER LAST_TIME_BOILER_ONOFF
    LIVING_ROOM  : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True,  datetime.datetime(1970, 1, 1, 9, 0)],
    BED_ROOM     : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True,  datetime.datetime(1970, 1, 1, 9, 0)],
    COMPUTER_ROOM: [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True,  datetime.datetime(1970, 1, 1, 9, 0)],
    HANS_ROOM    : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True,  datetime.datetime(1970, 1, 1, 9, 0)],
}


sensor_map = {
    # ROOM          TARGET                  CURRENT                 OUT_PIPE
    LIVING_ROOM  : ['LIVING_ROOM_TARGET',   'LIVING_ROOM_SENSOR',   'OUT_LIVING_ROOM0_SENSOR',  ],
    BED_ROOM     : ['BED_ROOM_TARGET',      'BED_ROOM_SENSOR',      'OUT_BED_ROOM_SENSOR',      ],
    COMPUTER_ROOM: ['COMPUTER_ROOM_TARGET', 'COMPUTER_ROOM_SENSOR', 'OUT_COMPUTER_ROOM_SENSOR', ],
    HANS_ROOM    : ['HANS_ROOM_TARGET',     'HANS_ROOM_SENSOR',     'OUT_HANS_ROOM_SENSOR',     ],
}
"""


class FlaskStopException(Exception):
    pass


def signal_handler(sig, frame):
    log.info("signal_handler: SIGINT")

    if scheduler:
        scheduler.resume_job('db_close')
    else:
        raise FlaskStopException()


def db_update():
    for room in ROOMS:
        if thermostat_states[room][STATE_DATA_MISSING_COUNT] == 0:
            thermostat_db.insert_sensor_data(room,
                                             thermostat_states[room][STATE_DTIME],
                                             thermostat_states[room][STATE_TEMPERATURE],
                                             thermostat_states[room][STATE_HUMIDITY],
                                             thermostat_states[room][STATE_PIPE_IN],
                                             thermostat_states[room][STATE_PIPE_OUT],
                                             thermostat_states[room][STATE_TEMPERATURE],
                                             thermostat_states[room][STATE_BOILER])

"""
def db_update():
    global last_temperatures_and_humidities
    for sensor_name, (temperature, humidity) in last_temperatures_and_humidities.items():
        thermostat_db.insert_sensor_data(datetime.datetime.now(), sensor_name, temperature, humidity)
"""

def read_temperatures():
    log.info("TASK - Updating sensor data")

    global thermostat_states

    def read_temperature(room, url):
        return room, requests.get(url, timeout=5).json()

    temperatures = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = (executor.submit(read_temperature, room, url) for room, url in temperature_servers.items())
        for idx, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                room, result = future.result()
            except Exception as exc:
                log.critical(f"Can't get data from server {room}:\n {exc}")

            temperatures[room] = result

    log.info(pformat(temperatures))

    current_time = datetime.datetime.now()

    for room in ROOMS:
        try:
            if not temperatures[room]['error'] and not temperatures[PIPES_BOILER][OUT_PIPE_NAME[room]]['error'] and not temperatures[PIPES_BOILER]['PIPE_IN_MAIN']['error']:
                thermostat_states[room][STATE_DTIME]                = current_time
                thermostat_states[room][STATE_TEMPERATURE]          = temperatures[room]['temperature']
                thermostat_states[room][STATE_HUMIDITY]             = temperatures[room]['humidity']
                thermostat_states[room][STATE_PIPE_IN]              = temperatures[PIPES_BOILER]['PIPE_IN_MAIN']['temperature']
                thermostat_states[room][STATE_PIPE_OUT]             = temperatures[PIPES_BOILER][OUT_PIPE_NAME[room]]['temperature']
                thermostat_states[room][STATE_DATA_MISSING_COUNT]   = 0
            else:
                thermostat_states[room][STATE_DATA_MISSING_COUNT] += 1
        except KeyError:
            thermostat_states[room][STATE_DATA_MISSING_COUNT] += 1

    log.info(pformat(thermostat_states))

"""
def update_sensor_states():
    log.info("TASK - Updating sensor data")

    global states
    global last_temperatures_and_humidities

    with lock:
        last_temperatures_and_humidities = {}

        for url in temperature_servers:
            try:
                temperature_and_humidity = json.loads(urllib.request.urlopen(url, timeout=3).read().decode('utf-8'))
                last_temperatures_and_humidities.update(temperature_and_humidity)
            except urllib.error.URLError:
                log.error("Temperature server does not exist: {}".format(url))

        for room in ROOMS:
            if not sensor_map[room][CURRENT] in last_temperatures_and_humidities:
                log.info("{} - Set pseudo room temperature to 20".format(sensor_map[room][CURRENT]))
                last_temperatures_and_humidities.update({sensor_map[room][CURRENT]: [20.0, 0.0]})

            if not sensor_map[room][OUT_PIPE] in last_temperatures_and_humidities:
                log.info("{} - Set pseudo boiler temperature to 5".format(sensor_map[room][OUT_PIPE]))
                last_temperatures_and_humidities.update({sensor_map[room][OUT_PIPE]: [OUT_PIPE_FAILURE_TEMPERATURE, 0.0]})

        log.info('Sensor data\n' + str(last_temperatures_and_humidities))

        for room in ROOMS:
            states[room][CURRENT]   = last_temperatures_and_humidities[sensor_map[room][CURRENT]]
            states[room][OUT_PIPE]  = last_temperatures_and_humidities[sensor_map[room][OUT_PIPE]]
"""

def update_targets(new_targets):
    global thermostat_states

    with lock:
        for room in ROOMS:
            thermostat_states[room][STATE_TARGET] = new_targets[room]


def update_boilers(new_onoffs):
    global thermostat_states

    with lock:
        for room in ROOMS:
            if thermostat_states[room][STATE_BOILER] != new_onoffs[room]:
                log.info(f"{room}: state changed from {thermostat_states[room][STATE_BOILER]} to {new_onoffs[room]}")
            thermostat_states[room][STATE_BOILER] = new_onoffs[room]



def send_state_changes(old_onoffs, new_onoffs):
    with lock:
        log.info("Calling change_states: {} -> {}".format(old_onoffs, new_onoffs))
        change_states(old_onoffs, new_onoffs)


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', **states)


@app.route('/apply', methods=['POST', 'GET'])
def apply():
    log.info("Apply: {}".format(request.form))
    new_targets = {}
    auto_offs = set()
    for name, value in request.form.items():
        if name.endswith("_TARGET"):
            new_targets[name.replace("_TARGET", "")] = float(value)
        elif name.endswith("_AUTO_OFF"):
            auto_offs.add(name.replace("_AUTO_OFF", ""))

    update_targets(new_targets)

    temperature_keeping_task()

    return redirect(url_for('index'))


def temperature_keeping_task():
    log.info("TASK - Temperature Keeping Task")

    global thermostat_states

    PIPE_OUT_HIGH_LIMIT = 40.0
    PIPE_OUT_LOW_LIMIT = 35.0

    TARGET_HIGH_MARGIN = 0.5

    new_boiler_states = {room: thermostat_states[room][STATE_BOILER] for room in ROOMS}

    for room in ROOMS:
        target_base = thermostat_states[room][STATE_TARGET]
        target_high = target_base + TARGET_HIGH_MARGIN

        current = thermostat_states[room][STATE_TEMPERATURE]

        pipe_out = thermostat_states[room][STATE_PIPE_OUT]

        log.info("=== {} {:.2f}/{:.2f} | {:.2f}".format(room, current, target_base, pipe_out))

        if pipe_out >= PIPE_OUT_HIGH_LIMIT or current >= target_high:
            # Turn off boiler
            log.info("Should be OFF: current({:.2f}), target({:.2f}), out({:.2f})".format(current, target_base, pipe_out))
            new_boiler_states[room] = False
        elif pipe_out < PIPE_OUT_LOW_LIMIT and current < target_base:
            # Turn on boiler
            log.info("Should be ON: current({:.2f}), target({:.2f}), out({:.2f})".format(current, target_base, pipe_out))
            new_boiler_states[room] = True
            pass

    send_state_changes([thermostat_states[room][STATE_BOILER] for room in ROOMS],
                       [new_boiler_states[room] for room in ROOMS])

    update_boilers(new_boiler_states)

"""
def temperature_keeping_task2():
    log.info("TASK - Temperature Keeping Task")

    new_onoffs = {}
    for room in ROOMS:
        target = states[room][TARGET]
        current = states[room][CURRENT][0]
        out = states[room][OUT_PIPE][0]
        log.info("=== {} {:.2f}/{:.2f} | {:.2f}".format(room, current, target, out))
        if current < target and out < OUT_PIPE_TEMPERATURE_LIMIT + (target - 20):
            log.info("Should be ON: current({:.2f}), target({:.2f}), out({:.2f})".format(current, target, out))
            new_onoffs[room] = True
        elif current >= target or out >= OUT_PIPE_TEMPERATURE_LIMIT + (target - 20):
            log.info("Should be OFF: current({:.2f}), target({:.2f}), out({:.2f})".format(current, target, out))
            new_onoffs[room] = False
        else:
            raise AssertionError("Can't happen")

    send_state_changes([states[room][BOILER] for room in ROOMS],
                       [new_onoffs[room] for room in ROOMS])

    update_boilers(new_onoffs)
"""


def setup_logger(logger_name, log_dir_name, log_file_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    try:
        os.makedirs(log_dir_name)
    except FileExistsError:
        pass

    fh = TimedRotatingFileHandler(os.path.join(log_dir_name, log_file_name), when="midnight", backupCount=2)
    fh.setLevel(logging.NOTSET)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%H:%M:%S')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger


def listen_to_apscheduler(event):
    global scheduler

    if event.code == EVENT_JOB_ERROR:
        log.exception(event.exception)
        scheduler.shutdown(wait=True)
        scheduler = None


def db_close():
    log.info("db_close")

    global thermostat_db
    global scheduler

    thermostat_db.close()

    scheduler.shutdown(wait=False)
    scheduler = None


def db_open():
    log.info("db_open")

    global thermostat_db

    thermostat_db = ThermostatDatabase()
    thermostat_db.open()


def delete_old_db_files(days_before):
    db_file_directory_name = 'db'
    db_file_name = 'thermostat'
    db_file_ext = '.db'
    db_file_path = os.path.join(db_file_directory_name, db_file_name + db_file_ext)

    files_in_db_dir = os.listdir(db_file_directory_name)

    for file in files_in_db_dir:
        log.info(file)
        #dst = os.path.join(db_file_directory_name, '{file_name:}_{date:}{file_ext:}'.format(file_name=db_file_name, date=datetime.datetime.now().strftime('%Y-%m-%d'), file_ext=db_file_ext))


def db_rollover():
    thermostat_db.rollover()
    delete_old_db_files(14)


def thermostat_recovery():
    log.info("Prevent possible out of sync of living room state")
    with lock:
        if not thermostat_states[ROOM_LIVING][STATE_BOILER]:
            rotate_rotary_encoder(-40)
            time.sleep(6.0)


if __name__ == '__main__':
    thermostat_states[ROOM_LIVING][STATE_BOILER]    = True if sys.argv[1].lower() == 't' else False
    thermostat_states[ROOM_BED][STATE_BOILER]       = True if sys.argv[2].lower() == 't' else False
    thermostat_states[ROOM_COMPUTER][STATE_BOILER]  = True if sys.argv[3].lower() == 't' else False
    thermostat_states[ROOM_HANS][STATE_BOILER]      = True if sys.argv[4].lower() == 't' else False

    log = setup_logger(__name__, 'logs', 'thermostat.log')
    signal.signal(signal.SIGINT, signal_handler)

    gpio_init()

    scheduler = BackgroundScheduler(logger=log, executors={'default': ThreadPoolExecutor(1)})

    scheduler.add_listener(listen_to_apscheduler)

    # Initial update
    scheduler.add_job(db_open)
    scheduler.add_job(read_temperatures)
    scheduler.add_job(temperature_keeping_task)

    scheduler.add_job(db_close, next_run_time=None, id='db_close', misfire_grace_time=None)

    scheduler.add_job(read_temperatures,        'cron', second=0, minute='*', misfire_grace_time=15, coalesce=True)
    scheduler.add_job(db_update,                'cron', second=10, minute='*', misfire_grace_time=15, coalesce=True)
    scheduler.add_job(temperature_keeping_task, 'cron', second=20, minute='*/15', misfire_grace_time=120, coalesce=True)
    scheduler.add_job(db_rollover,              'cron', second=45, minute=59, hour=23, misfire_grace_time=120)

    scheduler.add_job(thermostat_recovery,      'cron', second=45, minute=1, hour='*', coalesce=True)

    scheduler.start()

    try:
        app.run(use_reloader=False, debug=True, host='0.0.0.0')
    except FlaskStopException:
        log.info("End of Flask app")

    log.info("End of Program")
