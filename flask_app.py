from flask import Flask, render_template, request, redirect, url_for
from collections import OrderedDict
from honeywell_dt200 import gpio_init, change_states, LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM
import threading
import datetime


app = Flask(__name__)
states = OrderedDict(
    [(LIVING_ROOM,      10.0),
     (BED_ROOM,         10.0),
     (COMPUTER_ROOM,    10.0),
     (HANS_ROOM,        10.0)]
)


def send_change_states_to_honeywell_dt200(old_states, new_states):
    newly_turned_on_rooms = []
    newly_turned_off_rooms = []
    old_honeywell_dt200_states = {}
    new_honeywell_dt200_states = {}
    for (room, old_state), (_, new_state) in zip(old_states.items(), new_states.items()):
        if old_state != new_state:
            old_honeywell_dt200_states[room] = 24.5 if old_state else 10.0
            new_honeywell_dt200_states[room] = 24.5 if new_state else 10.0
            if new_state:
                newly_turned_on_rooms.append(room)
            else:
                newly_turned_off_rooms.append(room)

    change_states(old_honeywell_dt200_states, new_honeywell_dt200_states)

    return newly_turned_on_rooms, newly_turned_off_rooms


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', **states)


@app.route('/apply', methods=['POST', 'GET'])
def apply():
    global states

    print(request.form)

    rooms_on = set()
    for room, on in request.form.items():
        rooms_on.add(room)

    new_states = OrderedDict()
    for room in states:
        if room in rooms_on:
            new_states[room] = True
        else:
            new_states[room] = False

    newly_turned_on_rooms, newly_turned_off_rooms = send_change_states_to_honeywell_dt200(states, new_states)

    states = new_states

    for newly_turned_off_room in newly_turned_off_rooms:
        # Should remove timer for the room
        # t.cancel()
        pass

    for newly_turned_on_room in newly_turned_on_rooms:
        # Should set timer for the room to turn off
        # t = threading.Timer(60 * 5, turn_off_room, [newly_turned_on_room]).start()
        pass

    return redirect(url_for('index'))


def turn_off_room(room):
    # Should be mutex protected
    # Call lock = threading.Lock() at init
    # with lock:
    global states

    send_change_states_to_honeywell_dt200({room: True}, {room: False})

    states[room] = False


if __name__ == '__main__':
    gpio_init()
    print("============ " + str(datetime.datetime.now()))
    app.run(debug=True, host='0.0.0.0')
