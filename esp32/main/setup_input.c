#include "setup_input.h"

#include <ctype.h>
#include <string.h>

setup_action_t setup_input_scan_hit(uint16_t x, uint16_t y, size_t page,
                                    size_t network_count)
{
    setup_action_t action = {0};
    if (y < 44 && x >= 350) {
        action.type = SETUP_ACTION_RESCAN;
        return action;
    }
    if (y >= 48 && y < 228) {
        size_t row = (y - 48) / 36;
        size_t index = page * SETUP_WIFI_ROWS_PER_PAGE + row;
        if (row < SETUP_WIFI_ROWS_PER_PAGE && index < network_count) {
            action.type = SETUP_ACTION_NETWORK;
            action.network_index = index;
        }
        return action;
    }
    if (y >= 230 && x < 110 && page > 0) action.type = SETUP_ACTION_PREVIOUS;
    if (y >= 230 && x >= 370 &&
        (page + 1) * SETUP_WIFI_ROWS_PER_PAGE < network_count) {
        action.type = SETUP_ACTION_NEXT;
    }
    return action;
}

static setup_action_t character_action(char character, bool uppercase)
{
    setup_action_t action = {.type = SETUP_ACTION_CHARACTER};
    action.character = uppercase ? (char)toupper((unsigned char)character) : character;
    return action;
}

setup_action_t setup_input_keyboard_hit(uint16_t x, uint16_t y, bool symbols,
                                        bool uppercase)
{
    static const char alpha_rows[][11] = {"1234567890", "qwertyuiop", "asdfghjkl"};
    static const char symbol_rows[][11] = {"!@#$%^&*()", "-_=+[]{}<>", ";:'\",.?/\\|"};
    setup_action_t action = {0};
    if (y >= 52 && y < 176) {
        size_t row = (y - 52) / 42;
        int start = row == 2 ? 28 : 5;
        int relative = (int)x - start;
        if (relative >= 0) {
            size_t column = (size_t)relative / 47;
            const char *values = symbols ? symbol_rows[row] : alpha_rows[row];
            if (column < strlen(values) && relative % 47 < 44) {
                return character_action(values[column], uppercase && !symbols && row > 0);
            }
        }
        return action;
    }
    if (y >= 178 && y < 218) {
        if (x < 62) {
            action.type = symbols ? SETUP_ACTION_SYMBOLS : SETUP_ACTION_SHIFT;
            return action;
        }
        if (x >= 385) {
            action.type = SETUP_ACTION_BACKSPACE;
            return action;
        }
        const char *values = symbols ? "`~" : "zxcvbnm";
        int step = symbols ? 47 : 44;
        int key_width = step - 3;
        int start = symbols ? 145 : 70;
        int relative = (int)x - start;
        if (relative >= 0) {
            size_t column = (size_t)relative / step;
            if (column < strlen(values) && relative % step < key_width) {
                return character_action(values[column], uppercase && !symbols);
            }
        }
        return action;
    }
    if (y >= 222) {
        if (x < 80) action.type = SETUP_ACTION_CANCEL;
        else if (x < 146) action.type = SETUP_ACTION_SYMBOLS;
        else if (x < 263) action.type = SETUP_ACTION_SPACE;
        else if (x < 347) action.type = SETUP_ACTION_SHOW_PASSWORD;
        else action.type = SETUP_ACTION_CONNECT;
    }
    return action;
}
