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
    puts("touch parser: OK");
    return 0;
}
