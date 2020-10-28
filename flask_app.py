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
STATE_TIME_BOILER_CHANGE = "STATE_TIME_BOILER_CHANGE"
STATE_DATA_MISSING_COUNT = "STATE_DATA_MISSING_COUNT"


# The order has a dependency to index.html
default_room_state = {
    STATE_DTIME:                datetime.datetime(1970, 1, 1, 9, 0),
    STATE_TEMPERATURE:          20.0,
    STATE_HUMIDITY:             50.0,
    STATE_PIPE_IN:              28.0,
    STATE_PIPE_OUT:             20.0,
    STATE_TARGET:               THERMOSTAT_OFF_TEMPERATURE,
    STATE_BOILER:               False,
    STATE_TIME_BOILER_CHANGE:   datetime.datetime(1970, 1, 1, 9, 0),
    STATE_DATA_MISSING_COUNT:   999999
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
    ROOM_COMPUTER:  "http://192.168.50.36/temperature",
    ROOM_HANS:      "http://192.168.50.37/temperature"
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


max_data_missing = 0

class FlaskStopException(Exception):
    pass


def signal_handler(sig, frame):
    log.info("signal_handler: SIGINT")

    if scheduler:
        scheduler.resume_job('db_close')
    else:
        raise FlaskStopException()


def initial_read_temperatures():
    while not all(thermostat_states[room][STATE_DATA_MISSING_COUNT] == 0 for room in ROOMS):
        read_temperatures()
        time.sleep(30)


def db_update():
    for room in ROOMS:
        #if thermostat_states[room][STATE_DATA_MISSING_COUNT] == 0:
            thermostat_db.insert_sensor_data(room,
                                             thermostat_states[room][STATE_DTIME],
                                             thermostat_states[room][STATE_TEMPERATURE],
                                             thermostat_states[room][STATE_HUMIDITY],
                                             thermostat_states[room][STATE_PIPE_IN],
                                             thermostat_states[room][STATE_PIPE_OUT],
                                             thermostat_states[room][STATE_TEMPERATURE],
                                             thermostat_states[room][STATE_BOILER],
                                             thermostat_states[room][STATE_DATA_MISSING_COUNT])

def periodic_task():
    read_temperatures()
    db_update()
    temperature_keeping_task()

def read_temperatures():
    log.info("TASK - Updating sensor data")

    global max_data_missing
    global thermostat_states

    def fetch_temperature(room, url):
        try:
            resp = requests.get(url, headers={'Connection': 'keep-alive'}, timeout=33).json()
        except Exception as exc:
            log.critical(f"Can't get data from server {room}:\n {exc}")
            resp = None
        return room, resp

    temperatures = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = (executor.submit(fetch_temperature, room, url) for room, url in temperature_servers.items())
        for idx, future in enumerate(concurrent.futures.as_completed(futures)):
            room, result = future.result()
            if result is not None:
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
                max_data_missing = max(max_data_missing, thermostat_states[room][STATE_DATA_MISSING_COUNT])
        except KeyError:
            thermostat_states[room][STATE_DATA_MISSING_COUNT] += 1
            max_data_missing = max(max_data_missing, thermostat_states[room][STATE_DATA_MISSING_COUNT])

    log.info(pformat(thermostat_states))
    log.info("Max data missing: " + str(max_data_missing) + " " + pformat([thermostat_states[room][STATE_DATA_MISSING_COUNT] for room in ROOMS]))


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
                thermostat_states[room][STATE_TIME_BOILER_CHANGE] = datetime.datetime.now()
                thermostat_states[room][STATE_BOILER] = new_onoffs[room]



def send_state_changes(old_onoffs, new_onoffs):
    with lock:
        log.info("Calling change_states: {} -> {}".format(old_onoffs, new_onoffs))
        change_states(old_onoffs, new_onoffs)


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', **thermostat_states)


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

    BOILER_STATE_CHANGE_DELAY = datetime.timedelta(minutes=5)
    MAX_BOILER_ON_TIME = datetime.timedelta(minutes=12)

    new_boiler_states = {room: thermostat_states[room][STATE_BOILER] for room in ROOMS}

    for room in ROOMS:
        boiler_state = thermostat_states[room][STATE_BOILER]
        target_base = thermostat_states[room][STATE_TARGET]
        target_high = target_base + TARGET_HIGH_MARGIN

        current = thermostat_states[room][STATE_TEMPERATURE]

        pipe_out = thermostat_states[room][STATE_PIPE_OUT]

        time_passed_after_boiler_state_change = datetime.datetime.now() - thermostat_states[room][STATE_TIME_BOILER_CHANGE]

        log.info("=== {} {:.2f}/{:.2f} | {:.2f} | {}".format(room, current, target_base, pipe_out, str(time_passed_after_boiler_state_change)))

        if boiler_state and \
           (pipe_out >= PIPE_OUT_HIGH_LIMIT or
           current >= target_high or
           time_passed_after_boiler_state_change >= MAX_BOILER_ON_TIME):
            # Turn off boiler
            log.info("Should be OFF: current({:.2f}), target({:.2f}), out({:.2f}, tdelta({}))".format(current, target_base, pipe_out, str(time_passed_after_boiler_state_change)))
            new_boiler_states[room] = False
        elif not boiler_state and \
             (pipe_out < PIPE_OUT_LOW_LIMIT and
             current < target_base and
             time_passed_after_boiler_state_change >= BOILER_STATE_CHANGE_DELAY):
            # Turn on boiler
            log.info("Should be ON: current({:.2f}), target({:.2f}), out({:.2f}, tdelta({}))".format(current, target_base, pipe_out, str(time_passed_after_boiler_state_change)))
            new_boiler_states[room] = True
            pass

    send_state_changes([thermostat_states[room][STATE_BOILER] for room in ROOMS],
                       [new_boiler_states[room] for room in ROOMS])

    update_boilers(new_boiler_states)


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

    initial_read_temperatures()

    max_data_missing = 0

    # Initial update
    scheduler.add_job(db_open)
    scheduler.add_job(db_close, next_run_time=None, id='db_close', misfire_grace_time=None)

    scheduler.add_job(periodic_task,        'cron', second=0, minute='*', misfire_grace_time=15, coalesce=True)
    scheduler.add_job(db_rollover,          'cron', second=45, minute=59, hour=23, misfire_grace_time=120)
    scheduler.add_job(thermostat_recovery,  'cron', second=45, minute=1, hour='*', coalesce=True)

    scheduler.start()

    try:
        app.run(use_reloader=False, debug=True, host='0.0.0.0')
    except FlaskStopException:
        log.info("End of Flask app")

    log.info("End of Program")
