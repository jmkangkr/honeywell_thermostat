from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states, LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM
import threading
import datetime
import sys
import time
import urllib.request


app = Flask(__name__)


OFF_TEMPERATURE_VALUE = 15.0
AUTO_OFF_TIMER_IN_SECONDS = 60 * 10

states = {
    LIVING_ROOM:    OFF_TEMPERATURE_VALUE,
    BED_ROOM:       OFF_TEMPERATURE_VALUE,
    COMPUTER_ROOM:  OFF_TEMPERATURE_VALUE,
    HANS_ROOM:      OFF_TEMPERATURE_VALUE
}


current_temperatures = {
    'BED_ROOM_TEMPERATURE': 30.0
}

timers_to_turn_off = {
    LIVING_ROOM:    None,
    BED_ROOM:       None,
    COMPUTER_ROOM:  None,
    HANS_ROOM:      None
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
    temperature_and_humidity = urllib.request.urlopen("http://192.168.0.25:5000").read()
    print(temperature_and_humidity)
    return render_template('index.html', **states, **current_temperatures)


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
    states[LIVING_ROOM]     = float(sys.argv[1])
    states[BED_ROOM]        = float(sys.argv[2])
    states[COMPUTER_ROOM]   = float(sys.argv[3])
    states[HANS_ROOM]       = float(sys.argv[4])

    gpio_init()
    print("============ " + str(datetime.datetime.now()))
    app.run(debug=True, host='0.0.0.0')
