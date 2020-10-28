import RPi.GPIO as GPIO
import time
import logging


log = None


# GPIO pin number for buttons and rotary encoder
_BUTTON_HEATING_LEAVING_OFF = 11
_BUTTON_MODE                = 13
_BUTTON_ROOM_SELECT         = 15
_ROTARY_ENCODER_PIN_A       = 38
_ROTARY_ENCODER_PIN_B       = 40


# Time in seconds for short/long press button
_SHORT_PRESS_TIME   = 0.1
_LONG_PRESS_TIME    = 4.0


_LIVING_ROOM     = 'LIVING_ROOM'
_BED_ROOM        = 'BED_ROOM'
_COMPUTER_ROOM   = 'COMPUTER_ROOM'
_HANS_ROOM       = 'HANS_ROOM'


#         Geo-sil      Bang1       Bang2           Bang3
_ROOMS = [_LIVING_ROOM, _BED_ROOM, _COMPUTER_ROOM, _HANS_ROOM]


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
    global log

    log = logging.getLogger(__name__)

    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(_BUTTON_HEATING_LEAVING_OFF, GPIO.OUT)
    GPIO.setup(_BUTTON_MODE, GPIO.OUT)
    GPIO.setup(_BUTTON_ROOM_SELECT, GPIO.OUT)
    GPIO.setup(_ROTARY_ENCODER_PIN_A, GPIO.OUT)
    GPIO.setup(_ROTARY_ENCODER_PIN_B, GPIO.OUT)


def rotate_rotary_encoder(count):
    if count > 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_A, _ROTARY_ENCODER_PIN_B, 0.025, count)
    elif count < 0:
        _rotary_encoder(_ROTARY_ENCODER_PIN_B, _ROTARY_ENCODER_PIN_A, 0.025, -count)


def change_states(old_states, new_states):
    log.info("State changes: {} -> {}".format(old_states, new_states))
    for index, room in enumerate(_ROOMS):
        log.info("=== {} ===".format(room))
        if room == _LIVING_ROOM:
            if new_states[index] and not old_states[index]:
                log.info("Turning ON")
                rotate_rotary_encoder(42)   # (THERMOSTAT_ON_TEMPERATURE - THERMOSTAT_OFF_TEMPERATURE) * 2
                time.sleep(6.0)
            elif not new_states[index] and old_states[index]:
                log.info("Turning OFF")
                rotate_rotary_encoder(-42)  # (THERMOSTAT_ON_TEMPERATURE - THERMOSTAT_OFF_TEMPERATURE) * 2
                time.sleep(6.0)
        else:
            if new_states[index] and not old_states[index]:
                log.info("Turning ON")
                _press_button_short(_BUTTON_HEATING_LEAVING_OFF)
                time.sleep(0.5)
            elif not new_states[index] and old_states[index]:
                log.info("Turning OFF")
                _press_button_short(_BUTTON_HEATING_LEAVING_OFF)
                time.sleep(0.5)

        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(0.5)

    log.info("========================")


if __name__ == '__main__':
    gpio_init()

    _room_selected = input("Select room\n0: living room\n1: Bedroom\n2: Lab 13485\n3: Han's room\n : ")
    _count = input("Input count to increase/decrease: ")

    for _room_index, _ in enumerate(_ROOMS):
        if int(_room_selected) == _room_index:
            rotate_rotary_encoder(int(_count))

        _press_button_short(_BUTTON_ROOM_SELECT)
        time.sleep(0.5)
