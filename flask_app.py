from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states, rotate_rotary_encoder
import threading
import sys
import urllib.request
import urllib.error
import json
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


log = None
scheduler = None
app = Flask(__name__)
lock = threading.Lock()
thermostat_db = None

OFF_TEMPERATURE = 5.0
ON_TEMPERATURE = 25.0

OUT_PIPE_TEMPERATURE_LIMIT = 33.0

LIVING_ROOM     = 'LIVING_ROOM'
BED_ROOM        = 'BED_ROOM'
COMPUTER_ROOM   = 'COMPUTER_ROOM'
HANS_ROOM       = 'HANS_ROOM'
ROOMS = (LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM)


TARGET      = 0
CURRENT     = 1
OUT_PIPE    = 2
BOILER      = 3


last_temperatures_and_humidities = None

states = {
    # ROOM          TARGET              CURRENT     OUT PIPE    BOILER
    LIVING_ROOM  : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True],
    BED_ROOM     : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True],
    COMPUTER_ROOM: [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True],
    HANS_ROOM    : [OFF_TEMPERATURE,    (0.0, 0.0), (0.0, 0.0), True],
}


sensor_map = {
    # ROOM          TARGET                  CURRENT                 OUT_PIPE
    LIVING_ROOM  : ['LIVING_ROOM_TARGET',   'LIVING_ROOM_SENSOR',   'OUT_LIVING_ROOM0_SENSOR',  ],
    BED_ROOM     : ['BED_ROOM_TARGET',      'BED_ROOM_SENSOR',      'OUT_BED_ROOM_SENSOR',      ],
    COMPUTER_ROOM: ['COMPUTER_ROOM_TARGET', 'COMPUTER_ROOM_SENSOR', 'OUT_COMPUTER_ROOM_SENSOR', ],
    HANS_ROOM    : ['HANS_ROOM_TARGET',     'HANS_ROOM_SENSOR',     'OUT_HANS_ROOM_SENSOR',     ],
}


temperature_servers = ("http://boiler-rpi:5000", "http://bedroom-rpi:5000", "http://hansroom-rpi:5000", "http://livingroom3-rpi:5000", "http://computerroom-rpi:5000")


class FlaskStopException(Exception):
    pass


def signal_handler(sig, frame):
    log.info("signal_handler: SIGINT")

    if scheduler:
        scheduler.resume_job('db_close')
    else:
        raise FlaskStopException()


def db_update():
    global last_temperatures_and_humidities
    for sensor_name, (temperature, humidity) in last_temperatures_and_humidities.items():
        thermostat_db.insert_sensor_data(datetime.datetime.now(), sensor_name, temperature, humidity)


def update_sensor_states():
    log.info("TASK - Updating sensor data")

    global states
    global last_temperatures_and_humidities

    with lock:
        last_temperatures_and_humidities = {}

        for url in temperature_servers:
            try:
                temperature_and_humidity = json.loads(urllib.request.urlopen(url).read().decode('utf-8'))
                last_temperatures_and_humidities.update(temperature_and_humidity)
            except urllib.error.URLError:
                log.error("Temperature server does not exist: {}".format(url))

        for room in ROOMS:
            if not sensor_map[room][CURRENT] in last_temperatures_and_humidities:
                log.info("{} - Set pseudo temperature to 20")
                last_temperatures_and_humidities.update({sensor_map[room][CURRENT]: [20.0, 0.0]})

        log.info('Sensor data\n' + str(last_temperatures_and_humidities))

        for room in ROOMS:
            states[room][CURRENT]   = last_temperatures_and_humidities[sensor_map[room][CURRENT]]
            states[room][OUT_PIPE]  = last_temperatures_and_humidities[sensor_map[room][OUT_PIPE]]


def update_targets(new_targets):
    global states

    with lock:
        for room in ROOMS:
            states[room][TARGET] = new_targets[room]


def update_boilers(new_onoffs):
    global states

    with lock:
        for room in ROOMS:
            states[room][BOILER] = new_onoffs[room]


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

    new_onoffs = {}
    for room in ROOMS:
        target = states[room][TARGET]
        current = states[room][CURRENT][0]
        out = states[room][OUT_PIPE][0]
        log.info("=== {} {:.2f}/{:.2f} | {:.2f}".format(room, current, target, out))
        if current < target and out < OUT_PIPE_TEMPERATURE_LIMIT:
            log.info("Should be ON")
            new_onoffs[room] = True
        elif current >= target or out >= OUT_PIPE_TEMPERATURE_LIMIT:
            log.info("Should be OFF")
            new_onoffs[room] = False
        else:
            raise AssertionError("Can't happen")

    send_state_changes([states[room][BOILER] for room in ROOMS],
                       [new_onoffs[room] for room in ROOMS])

    update_boilers(new_onoffs)


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

    files_in_db_dir = os.listdir("db_file_directory_name")

    for file in files_in_db_dir:
        log.info(file)
        #dst = os.path.join(db_file_directory_name, '{file_name:}_{date:}{file_ext:}'.format(file_name=db_file_name, date=datetime.datetime.now().strftime('%Y-%m-%d'), file_ext=db_file_ext))


def db_rollover():
    thermostat_db.rollover()
    delete_old_db_files(14)


def thermostat_recovery():
    log.info("Prevent possible out of sync of living room state")
    with lock:
        if not states[LIVING_ROOM][BOILER]:
            rotate_rotary_encoder(-40)
            time.sleep(6.0)


if __name__ == '__main__':
    states[LIVING_ROOM][BOILER] = True if sys.argv[1].lower() == 't' else False
    states[BED_ROOM][BOILER] = True if sys.argv[2].lower() == 't' else False
    states[COMPUTER_ROOM][BOILER] = True if sys.argv[3].lower() == 't' else False
    states[HANS_ROOM][BOILER] = True if sys.argv[4].lower() == 't' else False

    log = setup_logger(__name__, 'logs', 'thermostat.log')
    signal.signal(signal.SIGINT, signal_handler)

    gpio_init()

    scheduler = BackgroundScheduler(logger=log, executors={'default': ThreadPoolExecutor(1)})

    scheduler.add_listener(listen_to_apscheduler)

    # Initial update
    scheduler.add_job(db_open)
    scheduler.add_job(update_sensor_states)
    scheduler.add_job(temperature_keeping_task)

    scheduler.add_job(db_close, next_run_time=None, id='db_close', misfire_grace_time=None)

    scheduler.add_job(update_sensor_states,     'cron', second= 0, minute='*',    misfire_grace_time=15, coalesce=True)
    scheduler.add_job(db_update,                'cron', second=10, minute='*',    misfire_grace_time=15, coalesce=True)
    scheduler.add_job(temperature_keeping_task, 'cron', second=20, minute='*/15', misfire_grace_time=120, coalesce=True)
    scheduler.add_job(db_rollover,              'cron', second=45, minute=59, hour=23, misfire_grace_time=120)

    scheduler.add_job(thermostat_recovery,      'cron', second=45, minute=1, hour='*', coalesce=True)

    scheduler.start()

    try:
        app.run(use_reloader=False, debug=True, host='0.0.0.0')
    except FlaskStopException:
        log.info("End of Flask app")

    log.info("End of Program")
