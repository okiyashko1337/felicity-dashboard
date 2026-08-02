#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    DASH_PAGE_HOME = 0,
    DASH_PAGE_PV,
    DASH_PAGE_LOAD,
    DASH_PAGE_BATTERY,
    DASH_PAGE_GRID,
    DASH_PAGE_SYSTEM,
    DASH_PAGE_TODAY,
    DASH_PAGE_GAPS,
} dashboard_page_t;

typedef struct {
    uint8_t bytes[16];
    size_t length;
    unsigned ff_count;
} touch_parser_t;

void touch_parser_reset(touch_parser_t *parser);
bool touch_parser_feed(touch_parser_t *parser, uint8_t byte, dashboard_page_t *page);
dashboard_page_t touch_page_for_coordinates(dashboard_page_t current, uint16_t x, uint16_t y);
const char *touch_page_name(dashboard_page_t page);
