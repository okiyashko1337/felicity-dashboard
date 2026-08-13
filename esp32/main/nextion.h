#pragma once

#include <stddef.h>
#include <stdint.h>

#include "dashboard_data.h"
#include "touch_parser.h"

void nextion_init(void);
void nextion_command(const char *format, ...);
void nextion_text(int x, int y, int w, int h, int font, int color, int background,
                  const char *value);
void nextion_show_page(dashboard_page_t page);
void nextion_render_home(const dashboard_snapshot_t *snapshot, const dashboard_summary_t *summary, bool live);
void nextion_render_home_values(const dashboard_snapshot_t *snapshot,
                                const dashboard_summary_t *summary, bool live);
void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *snapshot,
                           const dashboard_summary_t *summary, bool live);
void nextion_render_detail_values(dashboard_page_t page,
                                  const dashboard_snapshot_t *snapshot,
                                  const dashboard_summary_t *summary, bool live);
void nextion_render_gaps(const dashboard_gaps_t *gaps, bool live);
void nextion_render_gaps_values(const dashboard_gaps_t *gaps, bool live);
void nextion_render_chart(dashboard_page_t page, const dashboard_chart_t *chart);
void nextion_render_clock(void);
bool nextion_read_page_change(dashboard_page_t *page);
bool nextion_read_touch(uint16_t *x, uint16_t *y);
bool nextion_read_touch_event(touch_event_t *event);
bool nextion_upload_begin(size_t size);
bool nextion_upload_chunk(const uint8_t *data, size_t size);
bool nextion_upload_finish(void);
