#include <assert.h>
#include <stdio.h>

#include "../main/setup_input.h"

int main(void)
{
    setup_action_t action = setup_input_scan_hit(20, 50, 0, 8);
    assert(action.type == SETUP_ACTION_NETWORK && action.network_index == 0);
    action = setup_input_scan_hit(20, 50, 1, 8);
    assert(action.type == SETUP_ACTION_NETWORK && action.network_index == 5);
    assert(setup_input_scan_hit(400, 10, 0, 8).type == SETUP_ACTION_RESCAN);
    assert(setup_input_scan_hit(400, 250, 0, 8).type == SETUP_ACTION_NEXT);
    assert(setup_input_scan_hit(20, 250, 1, 8).type == SETUP_ACTION_PREVIOUS);

    action = setup_input_keyboard_hit(5, 52, false, false);
    assert(action.type == SETUP_ACTION_CHARACTER && action.character == '1');
    action = setup_input_keyboard_hit(5, 94, false, true);
    assert(action.type == SETUP_ACTION_CHARACTER && action.character == 'Q');
    action = setup_input_keyboard_hit(52, 52, true, false);
    assert(action.type == SETUP_ACTION_CHARACTER && action.character == '@');
    assert(setup_input_keyboard_hit(400, 190, false, false).type == SETUP_ACTION_BACKSPACE);
    assert(setup_input_keyboard_hit(200, 240, false, false).type == SETUP_ACTION_SPACE);
    assert(setup_input_keyboard_hit(400, 240, false, false).type == SETUP_ACTION_CONNECT);
    puts("setup input: OK");
    return 0;
}
