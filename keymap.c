/* Copyright 2024 @ Keychron (https://www.keychron.com)
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "keycodes.h"
#include "keymap_us.h"
#include "quantum_keycodes.h"
#include QMK_KEYBOARD_H
#include "keychron_common.h"
#include "features/custom_shift_keys.h"
#include "features/key_signals.h"

enum layers {
    MAC_BASE,
    MAC_FN,
    WIN_BASE,
    WIN_FN,
};


enum custom_keycodes {
    CTL_B = SAFE_RANGE,
    CTL_G,
    CST_LCRLY,   // Custom Left Curly Brace
    CST_RCRLY,   // Custom Right Curly Brace
    CST_ALT_TAB, // Custom Alt+Tab for Mac
    AUTO_CLICK,  // Auto-clicking left mouse button
    MAC_PGUP,    // Macro: mQ
    MAC_PGDN,    // Macro: 'Q
    MAC_HOME,    // Macro: mW
    MAC_END,     // Macro: 'W
};

// https://getreuer.info/posts/keyboards/custom-shift-keys/index.html#add-custom-shift-keys-to-your-keymap
const custom_shift_key_t custom_shift_keys[] = {
    {KC_EXLM, KC_1},    // ! -> 1
    {KC_LBRC, KC_2},    // [ -> 2
    {CST_LCRLY, KC_3},  // { -> 3
    {KC_LPRN, KC_4},    // ( -> 4
    {KC_PERC, KC_5},    // % -> 5
    {KC_ASTR, KC_6},    // * -> 6
    {KC_AMPR, KC_7},    // & -> 7
    {KC_RPRN, KC_8},    // ) -> 8
    {CST_RCRLY, KC_9},  // } -> 9
    {KC_RBRC, KC_0},    // ] -> 0
    {KC_COLON, KC_SEMICOLON}, // : -> ;
    {KC_AT, KC_DLR},   // @ -> $
    {KC_HASH, KC_CIRC}, // # -> ^
};
uint8_t NUM_CUSTOM_SHIFT_KEYS = sizeof(custom_shift_keys) / sizeof(custom_shift_key_t);

// clang-format off
// https://docs.qmk.fm/keycodes
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
[MAC_BASE] = LAYOUT_ansi_84(
     KC_ESC,   KC_BRID,  KC_BRIU,  KC_MCTRL, KC_LNPAD, UG_VALD,  UG_VALU,  KC_MPRV,  KC_MPLY,  KC_MNXT,  KC_MUTE,  KC_VOLD,  KC_VOLU,  KC_SNAP,  KC_DEL,   UG_TOGG,
     KC_GRV,   KC_EXLM, KC_LBRC, CST_LCRLY, KC_LPRN, KC_PERC, KC_ASTR, KC_AMPR, KC_RPRN, CST_RCRLY, KC_RBRC,KC_MINS,KC_EQL,CTL_B,MAC_PGUP,
     KC_TAB,   KC_Q,     KC_W,     KC_E,     KC_R,     KC_T,     KC_Y,     KC_U,     KC_I,     KC_O,     KC_P,  KC_AT, KC_HASH,  KC_BSLS,            MAC_PGDN,
     KC_BSPC,  KC_A,     KC_S,     KC_D,     KC_F,     KC_G,     KC_H,     KC_J,     KC_K,     KC_L,     KC_COLON,  KC_QUOT,            KC_ENT,      MAC_HOME,
     KC_LSFT,            KC_Z,     KC_X,     KC_C,     KC_V,     KC_B,     KC_N,     KC_M,     KC_COMM,  KC_DOT,   KC_SLSH,           CTL_G,  KC_UP,    MAC_END,
     KC_LCTL,  KC_LOPTN, KC_LCMMD,                               KC_SPC,                                 KC_ESC,MO(MAC_FN),KC_ROPTN,  KC_LEFT,  KC_DOWN,  KC_RGHT),

[MAC_FN] = LAYOUT_ansi_84(
     _______,  KC_F1,    KC_F2,    KC_F3,    KC_F4,    KC_F5,    KC_F6,    KC_F7,    KC_F8,    KC_F9,    KC_F10,   KC_F11,   KC_F12,   _______,  _______,  UG_TOGG,
     _______,  BT_HST1,  BT_HST2,  BT_HST3,  P2P4G,    _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,            _______,
     UG_TOGG,  UG_NEXT,  UG_VALU,  UG_HUEU,  UG_SATU,  UG_SPDU,  _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,            _______,
     _______,  UG_PREV, UG_VALD,  UG_HUED,  UG_SATD,  UG_SPDD,  _______,  _______,  _______,  _______,  _______,  _______,            _______,            _______,
     _______,            _______,  _______,  _______,  _______,  BAT_LVL,  NK_TOGG,  _______,  _______,  _______,  _______,            _______,  _______,  _______,
     _______,  _______,  _______,                                _______,                                _______,  _______,  _______,  _______,  _______,  _______),

[WIN_BASE] = LAYOUT_ansi_84(
     KC_ESC,   KC_F1,    KC_F2,    KC_F3,    KC_F4,    KC_F5,    KC_F6,    KC_F7,    KC_F8,    KC_F9,    KC_F10,   KC_F11,   KC_F12,   AUTO_CLICK,  KC_DEL,   UG_NEXT,
     KC_GRV,   KC_1,     KC_2,     KC_3,     KC_4,     KC_5,     KC_6,     KC_7,     KC_8,     KC_9,     KC_0,     KC_MINS,  KC_EQL,   KC_BSPC,            KC_PGUP,
     KC_TAB,   KC_Q,     KC_W,     KC_E,     KC_R,     KC_T,     KC_Y,     KC_U,     KC_I,     KC_O,     KC_P,     KC_LBRC,  KC_RBRC,  KC_BSLS,            KC_PGDN,
     KC_BSPC,  KC_A,     KC_S,     KC_D,     KC_F,     KC_G,     KC_H,     KC_J,     KC_K,     KC_L,     KC_SCLN,  KC_QUOT,            KC_ENT,             KC_HOME,
     KC_LSFT,            KC_Z,     KC_X,     KC_C,     KC_V,     KC_B,     KC_N,     KC_M,     KC_COMM,  KC_DOT,   KC_SLSH,            KC_RSFT,  KC_UP,    KC_END,
     KC_LCTL,  KC_LGUI,  KC_LALT,                                KC_SPC,                                 KC_RALT, MO(WIN_FN),KC_RCTL,  KC_LEFT,  KC_DOWN,  KC_RGHT),

[WIN_FN] = LAYOUT_ansi_84(
     _______,  KC_BRID,  KC_BRIU,  KC_TASK,  KC_FILE,  UG_VALD,  UG_VALU,  KC_MPRV,  KC_MPLY,  KC_MNXT,  KC_MUTE,  KC_VOLD,  KC_VOLU,  _______,  _______,  UG_TOGG,
     _______,  BT_HST1,  BT_HST2,  BT_HST3,  P2P4G,    _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,            _______,
     UG_TOGG,  UG_NEXT,  UG_VALU,  UG_HUEU,  UG_SATU,  UG_SPDU,  _______,  _______,  _______,  _______,  _______,  _______,  _______,  _______,            _______,
     _______,  UG_PREV, UG_VALD,  UG_HUED,  UG_SATD,  UG_SPDD,  _______,  _______,  _______,  _______,  _______,  _______,            _______,            _______,
     _______,            _______,  _______,  _______,  _______,  BAT_LVL,  NK_TOGG,  _______,  _______,  _______,  _______,            _______,  _______,  _______,
     _______,  _______,  _______,                                _______,                                _______,  _______,  _______,  _______,  _______,  _______)
};

// clang-format on
// Track whether Left Shift is currently held
static bool lshift_held = false;

// Auto-click variables
static bool auto_click_active = false;
static uint16_t auto_click_timer = 0;

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    if (!process_custom_shift_keys(keycode, record)) { return false; }

    switch (keycode) {
        case AUTO_CLICK:
            if (record->event.pressed) {
                // Key pressed - start auto-clicking
                auto_click_active = true;
                auto_click_timer = timer_read();
                tap_code(MS_BTN1); // Click immediately
            } else {
                // Key released - stop auto-clicking
                auto_click_active = false;
            }
            return false;

        case MAC_PGUP:
            if (record->event.pressed) {
                SEND_STRING("mQ");
            }
            return false;

        case MAC_PGDN:
            if (record->event.pressed) {
                SEND_STRING("'Q");
            }
            return false;

        case MAC_HOME:
            if (record->event.pressed) {
                SEND_STRING("mW");
            }
            return false;

        case MAC_END:
            if (record->event.pressed) {
                SEND_STRING("'W");
            }
            return false;

        case CST_ALT_TAB:
            if (record->event.pressed) {
                register_code(KC_LCMD);
                tap_code(KC_TAB);
                unregister_code(KC_LCMD);
             }
            return false; // suppress default behavior


        case KC_LSFT:
            lshift_held = record->event.pressed;
            break;

        case KC_RSFT:
            if (record->event.pressed) {
                if (lshift_held) {
                    // If Left Shift is held, send Ctrl+Y instead of RShift
                    SEND_STRING(SS_LCTL("y"));
                    return false; // suppress default RShift
                }
            }
            break; // allow RShift to work normally if LShift not held

        case CST_LCRLY:
            if (record->event.pressed) {
                SEND_STRING("{");
            }
            return false;

        case CST_RCRLY:
            if (record->event.pressed) {
                SEND_STRING("}");
            }
            return false;

        case CTL_B:
            if (record->event.pressed) {
                SEND_STRING(SS_LCTL("b"));  // Sends Ctrl+B
            }
            return false;
        break;

        case CTL_G:
            if (record->event.pressed) {
                SEND_STRING(SS_LCTL("g"));  // Sends Ctrl+G
            }
            return false;
        break;

    }

    // Keychron's own key handling (Mac keys, BT host, etc.) runs after this
    // in process_record_kb, so it must not be called here as well.
    return true;
}

void matrix_scan_user(void) {
    if (auto_click_active) {
        if (timer_elapsed(auto_click_timer) >= 250) {
            tap_code(MS_BTN1); // Send left click
            auto_click_timer = timer_read(); // Reset timer
        }
    }
}

bool rgb_matrix_indicators_advanced_user(uint8_t led_min, uint8_t led_max) {
    key_signals_render(led_min, led_max);
    return true;
}
