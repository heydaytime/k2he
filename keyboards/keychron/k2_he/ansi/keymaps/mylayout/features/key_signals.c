#include "key_signals.h"
#include "via.h"

#define KEY_SIGNAL_BLINK_MS 500
#define KEY_SIGNAL_PULSE_MS 1500
// Signals follow the backlight brightness, but never dimmer than this.
#define KEY_SIGNAL_MIN_BRIGHTNESS 96

typedef struct {
    uint8_t  level;
    uint8_t  pattern;
    uint8_t  r, g, b;
    bool     expires;
    uint32_t expires_at;
} key_signal_t;

static key_signal_t signals[RGB_MATRIX_LED_COUNT];

static void set_signal(uint8_t *args, uint8_t *status) {
    uint8_t  row     = args[0];
    uint8_t  col     = args[1];
    uint8_t  level   = args[2];
    uint8_t  pattern = args[3];
    uint16_t ttl_s   = (args[4] << 8) | args[5];

    if (row >= MATRIX_ROWS || col >= MATRIX_COLS || g_led_config.matrix_co[row][col] == NO_LED) {
        *status = KEY_SIGNAL_STATUS_BAD_KEY;
        return;
    }
    if (level > KEY_SIGNAL_CUSTOM || pattern > KEY_SIGNAL_PULSE) {
        *status = KEY_SIGNAL_STATUS_BAD_VALUE;
        return;
    }

    key_signal_t *s = &signals[g_led_config.matrix_co[row][col]];
    s->level        = level;
    s->pattern      = pattern;
    s->expires      = ttl_s != 0;
    s->expires_at   = timer_read32() + (uint32_t)ttl_s * 1000;

    switch (level) {
        case KEY_SIGNAL_GOOD:
            s->r = 0, s->g = 255, s->b = 0;
            break;
        case KEY_SIGNAL_WARN:
            s->r = 255, s->g = 170, s->b = 0;
            break;
        case KEY_SIGNAL_ALERT:
            s->r = 255, s->g = 0, s->b = 0;
            break;
        case KEY_SIGNAL_CUSTOM:
            s->r = args[6], s->g = args[7], s->b = args[8];
            break;
    }
    *status = KEY_SIGNAL_STATUS_OK;
}

// VIA routes custom-value packets on channels it doesn't own here.
void via_custom_value_command_kb(uint8_t *data, uint8_t length) {
    uint8_t *command_id = &data[0];
    uint8_t *channel_id = &data[1];
    uint8_t *command    = &data[2];
    uint8_t *status     = &data[3];
    uint8_t *args       = &data[4];

    if (*channel_id != id_custom_channel) {
        *command_id = id_unhandled;
        return;
    }

    switch (*command) {
        case KEY_SIGNAL_CMD_SET:
            set_signal(args, status);
            break;
        case KEY_SIGNAL_CMD_CLEAR_ALL:
            memset(signals, 0, sizeof(signals));
            *status = KEY_SIGNAL_STATUS_OK;
            break;
        case KEY_SIGNAL_CMD_INFO:
            args[0] = KEY_SIGNAL_PROTOCOL_VERSION;
            args[1] = MATRIX_ROWS;
            args[2] = MATRIX_COLS;
            *status = KEY_SIGNAL_STATUS_OK;
            break;
        default:
            *status = KEY_SIGNAL_STATUS_BAD_COMMAND;
            break;
    }
}

static uint8_t pattern_intensity(uint8_t pattern, uint32_t now) {
    switch (pattern) {
        case KEY_SIGNAL_BLINK:
            return (now / KEY_SIGNAL_BLINK_MS) % 2 ? 0 : 255;
        case KEY_SIGNAL_PULSE: {
            uint32_t phase = now % KEY_SIGNAL_PULSE_MS;
            uint32_t half  = KEY_SIGNAL_PULSE_MS / 2;
            uint32_t ramp  = phase < half ? phase : KEY_SIGNAL_PULSE_MS - phase;
            return 40 + ramp * (255 - 40) / half;
        }
        default:
            return 255;
    }
}

bool key_signals_active(void) {
    uint32_t now = timer_read32();
    for (uint8_t i = 0; i < RGB_MATRIX_LED_COUNT; i++) {
        key_signal_t *s = &signals[i];
        if (s->level != KEY_SIGNAL_OFF && !(s->expires && timer_expired32(now, s->expires_at))) {
            return true;
        }
    }
    return false;
}

void key_signals_render(uint8_t led_min, uint8_t led_max) {
    uint32_t now        = timer_read32();
    uint8_t  brightness = MAX(rgb_matrix_get_val(), KEY_SIGNAL_MIN_BRIGHTNESS);

    for (uint8_t i = led_min; i < led_max; i++) {
        key_signal_t *s = &signals[i];
        if (s->level == KEY_SIGNAL_OFF) continue;

        if (s->expires && timer_expired32(now, s->expires_at)) {
            s->level = KEY_SIGNAL_OFF;
            continue;
        }

        uint16_t scale = (uint16_t)brightness * pattern_intensity(s->pattern, now) / 255;
        rgb_matrix_set_color(i, s->r * scale / 255, s->g * scale / 255, s->b * scale / 255);
    }
}
