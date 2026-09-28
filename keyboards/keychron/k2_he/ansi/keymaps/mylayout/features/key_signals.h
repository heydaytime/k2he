/**
 * @file key_signals.h
 * @brief Key signals: let programs on the computer color individual keys.
 *
 * A host program sends 32-byte raw HID packets on VIA's custom channel
 * (channel 0, which no Keychron or VIA feature uses). The firmware keeps the
 * requested color per key and paints it over the current RGB effect. Signals
 * live in RAM only: they vanish on power-off, and each can expire on its own.
 *
 * Packet layout (host -> keyboard; the keyboard echoes it back with [3] set):
 *
 *   [0] 0x07          VIA id_custom_set_value (0x08 get_value is also accepted)
 *   [1] 0x00          VIA id_custom_channel
 *   [2] command       KEY_SIGNAL_CMD_*
 *   [3] status        written by the keyboard in the reply, KEY_SIGNAL_STATUS_*
 *   [4..] arguments
 *
 * KEY_SIGNAL_CMD_SET:   [4] row  [5] col  [6] level  [7] pattern
 *                       [8..9] ttl in seconds, big endian, 0 = until cleared
 *                       [10..12] r, g, b (only read for KEY_SIGNAL_CUSTOM)
 *                       Level KEY_SIGNAL_OFF clears that key.
 * KEY_SIGNAL_CMD_CLEAR_ALL: no arguments.
 * KEY_SIGNAL_CMD_INFO:  reply [4] protocol version  [5] rows  [6] cols
 *
 * Signals are only visible while the RGB backlight is on and awake.
 */

#pragma once

#include "quantum.h"

#define KEY_SIGNAL_PROTOCOL_VERSION 1

enum key_signal_command {
    KEY_SIGNAL_CMD_SET       = 0x01,
    KEY_SIGNAL_CMD_CLEAR_ALL = 0x02,
    KEY_SIGNAL_CMD_INFO      = 0x03,
};

enum key_signal_status {
    KEY_SIGNAL_STATUS_OK          = 0x00,
    KEY_SIGNAL_STATUS_BAD_COMMAND = 0x01,
    KEY_SIGNAL_STATUS_BAD_KEY     = 0x02, // row/col out of range or key has no LED
    KEY_SIGNAL_STATUS_BAD_VALUE   = 0x03, // unknown level or pattern
};

enum key_signal_level {
    KEY_SIGNAL_OFF    = 0,
    KEY_SIGNAL_GOOD   = 1, // green
    KEY_SIGNAL_WARN   = 2, // yellow
    KEY_SIGNAL_ALERT  = 3, // red, needs attention
    KEY_SIGNAL_CUSTOM = 4, // r, g, b from the packet
};

enum key_signal_pattern {
    KEY_SIGNAL_SOLID = 0,
    KEY_SIGNAL_BLINK = 1,
    KEY_SIGNAL_PULSE = 2,
};

/**
 * Paints active signals. Call from rgb_matrix_indicators_advanced_user():
 *
 *     bool rgb_matrix_indicators_advanced_user(uint8_t led_min, uint8_t led_max) {
 *         key_signals_render(led_min, led_max);
 *         return true;
 *     }
 */
void key_signals_render(uint8_t led_min, uint8_t led_max);
