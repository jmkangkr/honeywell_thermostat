from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states, LIVING_ROOM_TARGET, BED_ROOM_TARGET, COMPUTER_ROOM_TARGET, HANS_ROOM_TARGET
import threading
import datetime
import sys
import time
import urllib.request
import json


app = Flask(__name__)


OFF_TEMPERATURE_VALUE = 15.0
AUTO_OFF_TIMER_IN_SECONDS = 60 * 10

states = {
    LIVING_ROOM_TARGET:    OFF_TEMPERATURE_VALUE,
    BED_ROOM_TARGET:       OFF_TEMPERATURE_VALUE,
    COMPUTER_ROOM_TARGET:  OFF_TEMPERATURE_VALUE,
    HANS_ROOM_TARGET:      OFF_TEMPERATURE_VALUE
}


timers_to_turn_off = {
    LIVING_ROOM_TARGET:    None,
    BED_ROOM_TARGET:       None,
    COMPUTER_ROOM_TARGET:  None,
    HANS_ROOM_TARGET:      None
}


lock = threading.Lock()


def calc_changed_room(old_states, new_states):
    rooms_changed = set()
    for room in old_states:
        if old_states[room] != new_states[room]:
            rooms_changed.add(room)

    return rooms_changed


@app.route('/')
@app.route('/index')
def index():
    temperatures_and_humidities = {}

    for url in ["http://boiler-rpi:5000", "http://bedroom-rpi:5000", "http://hansroom-rpi:5000"]:
        temperature_and_humidity = json.loads(urllib.request.urlopen(url).read().decode('utf-8'))
        print(temperature_and_humidity)
        temperatures_and_humidities.update(temperature_and_humidity)

    print(temperature_and_humidity)

    return render_template('index.html', **states, **temperatures_and_humidities)


@app.route('/sync')
def sync():
    return render_template('sync.html', **states)


@app.route('/apply', methods=['POST', 'GET'])
def apply():
    global states
    global lock

    with lock:
        print("Apply: {}".format(request.form))
        new_states = {}
        auto_offs = set()
        for room, temperature in request.form.items():
            if room.endswith("AUTO_OFF"):
                if temperature == 'on':
                    auto_offs.add(room)
            else:
                new_states[room] = float(temperature)

        change_states(states, new_states)

        rooms_changed = calc_changed_room(states, new_states)

        print("new_states: {}".format(str(new_states)))
        print("rooms_changed: {}".format(str(rooms_changed)))
        print("auto_offs: {}".format(str(auto_offs)))

        for room in rooms_changed:
            if timers_to_turn_off[room]:
                print("Remove timer for {}".format(room))
                timers_to_turn_off[room].cancel()
                timers_to_turn_off[room] = None

            if (new_states[room] != OFF_TEMPERATURE_VALUE) and (room in auto_offs):
                print("Adding timer for {}".format(room))
                timers_to_turn_off[room] = threading.Timer(AUTO_OFF_TIMER_IN_SECONDS, callback_turn_off_room, [room]).start()

        states = new_states

        return redirect(url_for('index'))


@app.route('/force_sync', methods=['POST', 'GET'])
def force_sync():
    global states
    global lock

    with lock:
        print("Force sync: {}".format(request.form))
        new_states = {}
        for room, temperature in request.form.items():
            if room.endswith("AUTO_OFF"):
                pass
            else:
                new_states[room] = float(temperature)

        states = new_states

        return redirect(url_for('sync'))


def callback_turn_off_room(room):
    global states

    with lock:
        new_states = states.copy()
        new_states[room] = OFF_TEMPERATURE_VALUE

        print("Auto-off: {}".format(room))
        change_states(states, new_states)

        states = new_states

        timers_to_turn_off[room] = None

        time.sleep(2.0)


if __name__ == '__main__':
    states[LIVING_ROOM_TARGET]     = float(sys.argv[1])
    states[BED_ROOM_TARGET]        = float(sys.argv[2])
    states[COMPUTER_ROOM_TARGET]   = float(sys.argv[3])
    states[HANS_ROOM_TARGET]       = float(sys.argv[4])

    gpio_init()
    print("============ " + str(datetime.datetime.now()))
    app.run(use_reloader=False, debug=True, host='0.0.0.0')
