import RPi.GPIO as GPIO
import time


# GPIO pin number for buttons and rotary encoder
_BUTTON_HEATING_LEAVING_OFF = 11
_BUTTON_MODE                = 13
_BUTTON_ROOM_SELECT         = 15
_ROTARY_ENCODER_PIN_A       = 38
_ROTARY_ENCODER_PIN_B       = 40


# Time in seconds for short/long press button
_SHORT_PRESS_TIME   = 0.1
_LONG_PRESS_TIME    = 4.0


def _press_button(pin, duration):
    GPIO.output(pin, True)
    time.sleep(duration)
    GPIO.output(pin, False)


def _press_button_short(pin):
    _press_button(pin, _SHORT_PRESS_TIME)


def _press_button_long(pin):
    _press_button(pin, _LONG_PRESS_TIME)


def _old_rotary_encoder(pin_a, pin_b, secs_per_change, count):
    pin_a_sequence = [False, True, True, False]
    pin_b_sequence = [False, False, True, True]

    p_a = False
    p_b = False

    for n in range(count):
        for a, b in zip(pin_a_sequence, pin_b_sequence):
            if p_a != a:
                GPIO.output(pin_a, a)
            if p_b != b:
                GPIO.output(pin_b, b)

            time.sleep(secs_per_change)

            p_a = a
            p_b = b

        time.sleep(secs_per_change)

    GPIO.output(pin_a, False)
    GPIO.output(pin_b, False)


def _rotary_encoder(pin_a, pin_b, secs_per_change, count):
    pin_a_sequence = [False, True, True, False]
    pin_b_sequence = [False, False, True, True]

    p_a = False
    p_b = False
    for n in range(count):
        for a, b in zip(pin_a_sequence, pin_b_sequence):
            if (p_a != a) and (p_b != b):
                GPIO.output((pin_a, pin_b), (a, b))
            elif p_a != a:
                GPIO.output(pin_a, a)
            elif p_b != b:
                GPIO.output(pin_b, b)

            p_a = a
            p_b = b

            time.sleep(secs_per_change)

    GPIO.output((pin_a, pin_b), False)
    time.sleep(secs_per_change)


def gpio_init():
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(_BUTTON_HEATING_LEAVING_OFF, GPIO.OUT)
    GPIO.setup(_BUTTON_MODE, GPIO.OUT)
    GPIO.setup(_BUTTON_ROOM_SELECT, GPIO.OUT)
    GPIO.setup(_ROTARY_ENCODER_PIN_A, GPIO.OUT)
    GPIO.setup(_ROTARY_ENCODER_PIN_B, GPIO.OUT)


LIVING_ROOM     = 'LIVING_ROOM'
BED_ROOM        = 'BED_ROOM'
COMPUTER_ROOM   = 'COMPUTER_ROOM'
HANS_ROOM       = 'HANS_ROOM'

#                                       Geo-sil      Bang1     Bang2          Bang3
_ROOMS_ORDER_IN_HONEYWELL_THERMOSTAT = [LIVING_ROOM, BED_ROOM, COMPUTER_ROOM, HANS_ROOM]


def rotate_rotary_encoder(count):
    if count > 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_A, _ROTARY_ENCODER_PIN_B, 0.025, count)
    elif count < 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_B, _ROTARY_ENCODER_PIN_A, 0.025, -count)


def _round_to_half(number):
    return round(number * 2) / 2


def original_change_states(old_states, new_states):
    print("State changes: {} -> {}".format(old_states, new_states))
    for room in _ROOMS_ORDER_IN_HONEYWELL_THERMOSTAT:
        print("=== {} ===".format(room))
        try:
            new_temp = _round_to_half(new_states[room])
            old_temp = _round_to_half(old_states[room])
            count = int((new_temp - old_temp) * 2)
            print("rotate {} count (temp {})".format(count, float(count) / 2))
            if count != 0:
                rotate_rotary_encoder(count)
                time.sleep(6.0)
        except KeyError:
            pass

        print("move to next room")
        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(0.5)


def change_states(old_states, new_states):
    print("State changes: {} -> {}".format(old_states, new_states))
    for room in _ROOMS_ORDER_IN_HONEYWELL_THERMOSTAT:
        print("=== {} ===".format(room))
        try:
            new_temp = _round_to_half(new_states[room])
            old_temp = _round_to_half(old_states[room])
            if room == LIVING_ROOM:
                if new_temp == 25.0 and old_temp == 15.0:
                    rotate_rotary_encoder(20)
                elif new_temp == 15.0 and old_temp == 25.0:
                    rotate_rotary_encoder(-20)
                else:
                    raise AssertionError("Unkown temperature")
                time.sleep(6.0)
            else:
                if new_temp == 25.0 and old_temp == 15.0:
                    _press_button_short(_BUTTON_HEATING_LEAVING_OFF)
                elif new_temp == 15.0 and old_temp == 25.0:
                    _press_button_short(_BUTTON_HEATING_LEAVING_OFF)
                else:
                    raise AssertionError("Unkown temperature")
                time.sleep(0.25)
        except KeyError:
            pass

        print("move to next room")
        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(0.25)


if __name__ == '__main__':
    gpio_init()

    room = input("Select room\n0: living room\n1: Bedroom\n2: Lab 13485\n3: Han's room\n : ")
    count = input("Input count to increase/decrease: ")

    for i in range(0, int(room)):
        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(0.25)

    rotate_rotary_encoder(int(count))
