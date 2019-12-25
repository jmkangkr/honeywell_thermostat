from flask import Flask, render_template, request, redirect, url_for
from collections import OrderedDict


app = Flask(__name__)
states = OrderedDict(
    [('living room',     True),
     ('bedroom',         True),
     ('computer room',   False),
     ('kid room',        False)]
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

    for (room, state), (_, new_state) in zip(states.items(), new_states.items()):
        if state == new_state:
            print("{}: stay {}".format(room, state))
        else:
            print("{}: {} -> {}".format(room, state, new_state))

    states = new_states

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
