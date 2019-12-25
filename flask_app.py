from flask import Flask, render_template, request, redirect, url_for
from collections import OrderedDict
from honeywell_dt200 import gpio_init, change_states, LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM


app = Flask(__name__)
states = OrderedDict(
    [(LIVING_ROOM,      False),
     (BED_ROOM,         False),
     (COMPUTER_ROOM,    False),
     (HANS_ROOM,        False)]
)


@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', **states)


@app.route('/apply', methods=['POST', 'GET'])
def apply():
    global states

    rooms_on = set()
    for room, on in request.form.items():
        rooms_on.add(room)

    new_states = OrderedDict()
    for room in states:
        if room in rooms_on:
            new_states[room] = True
        else:
            new_states[room] = False

    old_honeywell_dt200_states = {}
    new_honeywell_dt200_states = {}
    for (room, state), (_, new_state) in zip(states.items(), new_states.items()):
        if state != new_state:
            old_honeywell_dt200_states[room] = 24.5 if state else 10.0
            new_honeywell_dt200_states[room] = 24.5 if new_state else 10.0

    print("change_states: {} -> {}".format(old_honeywell_dt200_states, new_honeywell_dt200_states))
    change_states(old_honeywell_dt200_states, new_honeywell_dt200_states)

    states = new_states

    return redirect(url_for('index'))


if __name__ == '__main__':
    gpio_init()
    app.run(debug=True, host='0.0.0.0')
