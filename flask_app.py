from flask import Flask, render_template, request, redirect, url_for
from honeywell_dt200 import gpio_init, change_states, LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM
import threading
import datetime
import sys


app = Flask(__name__)


states = {
    LIVING_ROOM:    10.0,
    BED_ROOM:       10.0,
    COMPUTER_ROOM:  10.0,
    HANS_ROOM:      10.0
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
    return render_template('index.html', **states)


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
        for room, temperature in request.form.items():
            if room.endswith("AUTO_TURNOFF"):
                pass
            else:
                new_states[room] = float(temperature)

        change_states(states, new_states)

        '''
        rooms_changed = calc_changed_room(states, new_states)

        for room in rooms_changed:
            if timers_to_turn_off[room]:
                timers_to_turn_off[room].cancel()
                timers_to_turn_off[room] = None

            if new_states[room] != 10.0:
                timers_to_turn_off[room] = threading.Timer(60 * 5, callback_turn_off_room, [room]).start()
                pass

        '''

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
            if room.endswith("AUTO_TURNOFF"):
                pass
            else:
                new_states[room] = float(temperature)

        states = new_states

        return redirect(url_for('sync'))


def callback_turn_off_room(room):
    global states

    with lock:
        new_states = states.copy()
        new_states[room] = 10.0

        print("Turning off {}".format(room))
        change_states(states, new_states)

        states = new_states

        timers_to_turn_off[room] = None


if __name__ == '__main__':
    states[LIVING_ROOM]     = float(sys.argv[1])
    states[BED_ROOM]        = float(sys.argv[2])
    states[COMPUTER_ROOM]   = float(sys.argv[3])
    states[HANS_ROOM]       = float(sys.argv[4])

    gpio_init()
    print("============ " + str(datetime.datetime.now()))
    app.run(debug=True, host='0.0.0.0')
