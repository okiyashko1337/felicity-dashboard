#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SETUP_WIFI_ROWS_PER_PAGE 5

typedef enum {
    SETUP_ACTION_NONE = 0,
    SETUP_ACTION_NETWORK,
    SETUP_ACTION_RESCAN,
    SETUP_ACTION_PREVIOUS,
    SETUP_ACTION_NEXT,
    SETUP_ACTION_CHARACTER,
    SETUP_ACTION_BACKSPACE,
    SETUP_ACTION_SHIFT,
    SETUP_ACTION_SYMBOLS,
    SETUP_ACTION_SPACE,
    SETUP_ACTION_CANCEL,
    SETUP_ACTION_CONNECT,
    SETUP_ACTION_SHOW_PASSWORD,
} setup_action_type_t;

typedef struct {
    setup_action_type_t type;
    size_t network_index;
    char character;
} setup_action_t;

setup_action_t setup_input_scan_hit(uint16_t x, uint16_t y, size_t page,
                                    size_t network_count);
setup_action_t setup_input_keyboard_hit(uint16_t x, uint16_t y, bool symbols,
                                        bool uppercase);

