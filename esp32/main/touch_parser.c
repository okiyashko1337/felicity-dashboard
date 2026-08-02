#include "touch_parser.h"

#include <string.h>

void touch_parser_reset(touch_parser_t *parser)
{
    memset(parser, 0, sizeof(*parser));
}

const char *touch_page_name(dashboard_page_t page)
{
    static const char *names[] = {"home", "pv", "load", "battery", "grid", "system", "today", "gaps"};
    return page <= DASH_PAGE_GAPS ? names[page] : "home";
}

dashboard_page_t touch_page_for_coordinates(dashboard_page_t current, uint16_t x, uint16_t y)
{
    if (current == DASH_PAGE_HOME) {
        if (y < 44 && x >= 260 && x <= 400) return DASH_PAGE_GAPS;
        if (y >= 50 && y <= 153) return x < 161 ? DASH_PAGE_PV : x < 318 ? DASH_PAGE_LOAD : DASH_PAGE_BATTERY;
        if (y >= 160 && y <= 271) return x < 161 ? DASH_PAGE_GRID : x < 318 ? DASH_PAGE_SYSTEM : DASH_PAGE_TODAY;
    } else if (x <= 84 && y < 44) {
        return DASH_PAGE_HOME;
    }
    return current;
}

static bool consume_frame(touch_parser_t *parser, dashboard_page_t *page)
{
    bool changed = false;
    if (parser->length >= 2 && parser->bytes[0] == 0x66 && parser->bytes[1] <= DASH_PAGE_GAPS) {
        dashboard_page_t next = (dashboard_page_t)parser->bytes[1];
        changed = next != *page;
        *page = next;
    } else if (parser->length >= 6 && (parser->bytes[0] == 0x67 || parser->bytes[0] == 0x68) && parser->bytes[5] == 0) {
        uint16_t x = ((uint16_t)parser->bytes[1] << 8) | parser->bytes[2];
        uint16_t y = ((uint16_t)parser->bytes[3] << 8) | parser->bytes[4];
        dashboard_page_t next = touch_page_for_coordinates(*page, x, y);
        changed = next != *page;
        *page = next;
    }
    touch_parser_reset(parser);
    return changed;
}

bool touch_parser_feed(touch_parser_t *parser, uint8_t byte, dashboard_page_t *page)
{
    if (byte == 0xff) {
        if (++parser->ff_count == 3) return consume_frame(parser, page);
        return false;
    }
    while (parser->ff_count && parser->length < sizeof(parser->bytes)) {
        parser->bytes[parser->length++] = 0xff;
        parser->ff_count--;
    }
    if (parser->length < sizeof(parser->bytes)) parser->bytes[parser->length++] = byte;
    return false;
}
