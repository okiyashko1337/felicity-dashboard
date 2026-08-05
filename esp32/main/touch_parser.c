#include "touch_parser.h"

#include <string.h>

void touch_parser_reset(touch_parser_t *parser)
{
    memset(parser, 0, sizeof(*parser));
}

const char *touch_page_name(dashboard_page_t page)
{
    static const char *names[] = {"home", "pv", "load", "battery", "grid", "system", "today", "gaps", "setup"};
    return page <= DASH_PAGE_SETUP ? names[page] : "home";
}

dashboard_page_t touch_page_for_coordinates(dashboard_page_t current, uint16_t x, uint16_t y)
{
    if (current == DASH_PAGE_HOME) {
        if (y < 36 && x < 31) return DASH_PAGE_SETUP;
        if (y < 44 && x >= 260 && x <= 400) return DASH_PAGE_GAPS;
        if (y >= 50 && y <= 153) return x < 161 ? DASH_PAGE_PV : x < 318 ? DASH_PAGE_LOAD : DASH_PAGE_BATTERY;
        if (y >= 160 && y <= 271) return x < 161 ? DASH_PAGE_GRID : x < 318 ? DASH_PAGE_SYSTEM : DASH_PAGE_TODAY;
    } else if (current == DASH_PAGE_SYSTEM && x >= 360 && y >= 44 && y < 110) {
        return DASH_PAGE_SETUP;
    } else if (current != DASH_PAGE_SETUP && x <= 84 && y < 44) {
        return DASH_PAGE_HOME;
    }
    return current;
}

static bool consume_event_frame(touch_parser_t *parser, touch_event_t *event)
{
    memset(event, 0, sizeof(*event));
    if (parser->length >= 2 && parser->bytes[0] == 0x66 && parser->bytes[1] <= DASH_PAGE_GAPS) {
        event->type = TOUCH_EVENT_PAGE;
        event->page = parser->bytes[1];
    } else if (parser->length >= 6 &&
               (parser->bytes[0] == 0x67 || parser->bytes[0] == 0x68)) {
        event->type = TOUCH_EVENT_COORDINATE;
        event->x = ((uint16_t)parser->bytes[1] << 8) | parser->bytes[2];
        event->y = ((uint16_t)parser->bytes[3] << 8) | parser->bytes[4];
        event->pressed = parser->bytes[5] != 0;
    }
    touch_parser_reset(parser);
    return event->type != TOUCH_EVENT_NONE;
}

bool touch_parser_feed_event(touch_parser_t *parser, uint8_t byte, touch_event_t *event)
{
    if (byte == 0xff) {
        if (++parser->ff_count == 3) return consume_event_frame(parser, event);
        return false;
    }
    while (parser->ff_count && parser->length < sizeof(parser->bytes)) {
        parser->bytes[parser->length++] = 0xff;
        parser->ff_count--;
    }
    if (parser->length < sizeof(parser->bytes)) parser->bytes[parser->length++] = byte;
    return false;
}

bool touch_parser_feed(touch_parser_t *parser, uint8_t byte, dashboard_page_t *page)
{
    touch_event_t event;
    if (!touch_parser_feed_event(parser, byte, &event)) return false;
    dashboard_page_t next = *page;
    if (event.type == TOUCH_EVENT_PAGE && event.page <= DASH_PAGE_GAPS) {
        next = (dashboard_page_t)event.page;
    } else if (event.type == TOUCH_EVENT_COORDINATE && !event.pressed) {
        next = touch_page_for_coordinates(*page, event.x, event.y);
    }
    bool changed = next != *page;
    *page = next;
    return changed;
}
