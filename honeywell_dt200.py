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


def _rotary_encoder(pin_a, pin_b, secs_per_change, count):
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


def _rotate_rotary_encoder(count):
    if count > 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_A, _ROTARY_ENCODER_PIN_B, 0.2, count)
    elif count < 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_B, _ROTARY_ENCODER_PIN_A, 0.2, -count)


def _round_to_0dot5(number):
    return round(number * 2) / 2


def change_states(old_states, new_states):
    for room in _ROOMS_ORDER_IN_HONEYWELL_THERMOSTAT:
        try:
            new_temp = _round_to_0dot5(new_states[room])
            old_temp = _round_to_0dot5(old_states[room])
            count = int((new_temp - old_temp) * 2)
            _rotate_rotary_encoder(count)
            time.sleep(1.0)
        except KeyError:
            pass
        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(1.0)
