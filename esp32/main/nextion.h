#pragma once

#include "dashboard_data.h"
#include "touch_parser.h"

void nextion_init(void);
void nextion_show_page(dashboard_page_t page);
void nextion_render_home(const dashboard_snapshot_t *snapshot, const dashboard_summary_t *summary, bool live);
void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *snapshot,
                           const dashboard_summary_t *summary, bool live);
void nextion_render_gaps(const dashboard_gaps_t *gaps, bool live);
void nextion_render_chart(dashboard_page_t page, const dashboard_chart_t *chart);
bool nextion_read_page_change(dashboard_page_t *page);
