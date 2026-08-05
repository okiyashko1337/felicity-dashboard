#pragma once

#include "dashboard_data.h"
#include "touch_parser.h"

typedef enum {
    NEXTION_EVENT_NONE = 0,
    NEXTION_EVENT_PAGE_CHANGE,
    NEXTION_EVENT_DISPLAY_READY,
} nextion_event_t;

typedef enum {
    NEXTION_DATA_NONE,
    NEXTION_DATA_LIVE,
    NEXTION_DATA_DEMO,
} nextion_data_state_t;

void nextion_init(void);
void nextion_show_page(dashboard_page_t page);
void nextion_render_clock(void);
void nextion_render_home(const dashboard_snapshot_t *snapshot, const dashboard_summary_t *summary,
                         nextion_data_state_t state);
void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *snapshot,
                           const dashboard_summary_t *summary, nextion_data_state_t state);
void nextion_render_gaps(const dashboard_gaps_t *gaps, nextion_data_state_t state);
void nextion_render_chart(dashboard_page_t page, const dashboard_chart_t *chart);
bool nextion_advance_chart(dashboard_page_t current_page, size_t max_samples);
nextion_event_t nextion_read_event(dashboard_page_t *page);
