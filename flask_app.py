from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states
import threading
import datetime
import urllib.request
import json
import atexit
import time
from apscheduler.schedulers.background import BackgroundScheduler


app = Flask(__name__)


OFF_TEMPERATURE = 10.0
ON_TEMPERATURE = 25.0

OUT_PIPE_TEMPERATURE_LIMIT = 32.0

LIVING_ROOM     = 'LIVING_ROOM'
BED_ROOM        = 'BED_ROOM'
COMPUTER_ROOM   = 'COMPUTER_ROOM'
HANS_ROOM       = 'HANS_ROOM'
ROOMS = (LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM)


TARGET      = 0
CURRENT     = 1
OUT_PIPE    = 2
BOILER      = 3


states = {
    # ROOM          TARGET              CURRENT     INPUT       BOILER
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


lock = threading.Lock()


def update_sensor_states():
    global states

    with lock:
        temperatures_and_humidities = {}

        for url in ["http://boiler-rpi:5000", "http://bedroom-rpi:5000", "http://hansroom-rpi:5000"]:
            temperature_and_humidity = json.loads(urllib.request.urlopen(url).read().decode('utf-8'))
            temperatures_and_humidities.update(temperature_and_humidity)

        temperatures_and_humidities.update({'LIVING_ROOM_SENSOR': [5.0, 0.0], 'COMPUTER_ROOM_SENSOR': [5.0, 0.0]})

        print(temperatures_and_humidities)

        for room in ROOMS:
            states[room][CURRENT]   = temperatures_and_humidities[sensor_map[room][CURRENT]]
            states[room][OUT_PIPE]  = temperatures_and_humidities[sensor_map[room][OUT_PIPE]]


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
        print("Calling change_states: {} -> {}".format(old_onoffs, new_onoffs))
        change_states(old_onoffs, new_onoffs)


@app.route('/')
@app.route('/index')
def index():
    update_sensor_states()
    return render_template('index.html', **states)


@app.route('/apply', methods=['POST', 'GET'])
def apply():
    global states

    with lock:
        print("Apply: {}".format(request.form))

        new_targets = {}
        auto_offs = set()
        for name, value in request.form.items():
            if name.endswith("_TARGET"):
                states[name.replace("_TARGET", "")][TARGET] = float(value)
            elif name.endswith("_AUTO_OFF"):
                auto_offs.add(name.replace("_AUTO_OFF", ""))

        update_targets(new_targets)

        temperature_keeping_task()

    return redirect(url_for('index'))


def temperature_keeping_task():
    print("{} Temperature Keeping Task".format(time.strftime("%Y-%m-%d %H:%M:%S")))

    update_sensor_states()

    new_onoffs = {}
    for room in ROOMS:
        target = states[room][TARGET]
        current = states[room][CURRENT][0]
        out = states[room][OUT_PIPE][0]
        print("=== {} {:.2f}/{:.2f} | {:.2f}".format(room, current, target, out))
        if current < target and out < OUT_PIPE_TEMPERATURE_LIMIT:
            print("Should be ON")
            new_onoffs[room] = True
        elif current >= target or out >= OUT_PIPE_TEMPERATURE_LIMIT:
            print("Should be OFF")
            new_onoffs[room] = False
        else:
            raise AssertionError("Can't happen")

    send_state_changes([states[room][BOILER] for room in ROOMS],
                       [new_onoffs[room] for room in ROOMS])

    update_boilers(new_onoffs)


if __name__ == '__main__':
    print("<Initial setup guide>")
    print("Turn on all rooms and set target temperatures to {:.1f}".format(ON_TEMPERATURE))
    input("Press Enter when ready...")

    gpio_init()

    temperature_keeping_task()

    scheduler = BackgroundScheduler()
    scheduler.add_job(temperature_keeping_task, 'cron', minute='*/10')
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

    app.run(use_reloader=False, debug=True, host='0.0.0.0')
