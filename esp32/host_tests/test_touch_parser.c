#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "../main/touch_parser.h"

static bool feed(touch_parser_t *parser, dashboard_page_t *page, const uint8_t *bytes, size_t size)
{
    bool changed = false;
    for (size_t i = 0; i < size; ++i) changed |= touch_parser_feed(parser, bytes[i], page);
    return changed;
}

int main(void)
{
    touch_parser_t parser;
    touch_parser_reset(&parser);
    dashboard_page_t page = DASH_PAGE_HOME;
    const uint8_t pv_touch[] = {0x67, 0x00, 0x50, 0x00, 0x64, 0x00, 0xff, 0xff, 0xff};
    assert(feed(&parser, &page, pv_touch, sizeof(pv_touch)));
    assert(page == DASH_PAGE_PV);

    const uint8_t back_touch[] = {0x67, 0x00, 0x20, 0x00, 0x10, 0x00, 0xff, 0xff, 0xff};
    assert(feed(&parser, &page, back_touch, sizeof(back_touch)));
    assert(page == DASH_PAGE_HOME);

    const uint8_t page_frame[] = {0x66, 0x04, 0xff, 0xff, 0xff};
    assert(feed(&parser, &page, page_frame, sizeof(page_frame)));
    assert(page == DASH_PAGE_GRID);

    touch_event_t event = {0};
    touch_parser_reset(&parser);
    bool received = false;
    for (size_t i = 0; i < sizeof(pv_touch); ++i) {
        received |= touch_parser_feed_event(&parser, pv_touch[i], &event);
    }
    assert(received);
    assert(event.type == TOUCH_EVENT_COORDINATE);
    assert(event.x == 80 && event.y == 100 && !event.pressed);

    const uint8_t press_touch[] = {0x67, 0x00, 0x50, 0x00, 0x64, 0x01, 0xff, 0xff, 0xff};
    received = false;
    for (size_t i = 0; i < sizeof(press_touch); ++i) {
        received |= touch_parser_feed_event(&parser, press_touch[i], &event);
    }
    assert(received);
    assert(event.type == TOUCH_EVENT_COORDINATE);
    assert(event.x == 80 && event.y == 100 && event.pressed);

    assert(touch_page_for_coordinates(DASH_PAGE_HOME, 15, 15) == DASH_PAGE_SETUP);
    assert(touch_page_for_coordinates(DASH_PAGE_HOME, 280, 175) == DASH_PAGE_SYSTEM);
    assert(touch_page_for_coordinates(DASH_PAGE_HOME, 200, 240) == DASH_PAGE_SYSTEM);
    assert(touch_page_for_coordinates(DASH_PAGE_SYSTEM, 420, 75) == DASH_PAGE_SETUP);
    assert(touch_page_for_coordinates(DASH_PAGE_PV, 30, 15) == DASH_PAGE_HOME);
    puts("touch parser: OK");
    return 0;
}
