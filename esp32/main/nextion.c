#include "nextion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "sdkconfig.h"

#if CONFIG_FELICITY_EMULATOR
static const char *TAG = "nextion";
#else
static const uart_port_t PORT = UART_NUM_1;
#endif
static touch_parser_t parser;

static void command(const char *format, ...)
{
    char text[192];
    va_list args;
    va_start(args, format);
    vsnprintf(text, sizeof(text), format, args);
    va_end(args);
#if CONFIG_FELICITY_EMULATOR
    ESP_LOGI(TAG, "NX> %s", text);
#else
    uart_write_bytes(PORT, text, strlen(text));
    static const uint8_t end[] = {0xff, 0xff, 0xff};
    uart_write_bytes(PORT, end, sizeof(end));
#endif
}

static void text(int x, int y, int w, int h, int font, int color, int background, const char *value)
{
    command("xstr %d,%d,%d,%d,%d,%d,%d,1,1,1,\"%s\"", x, y, w, h, font, color, background, value);
}

void nextion_init(void)
{
    touch_parser_reset(&parser);
#if !CONFIG_FELICITY_EMULATOR
    uart_config_t config = {
        .baud_rate = CONFIG_FELICITY_NEXTION_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(PORT, 1024, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(PORT, &config));
    ESP_ERROR_CHECK(uart_set_pin(PORT, CONFIG_FELICITY_NEXTION_TX_GPIO,
                                 CONFIG_FELICITY_NEXTION_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
#endif
}

void nextion_show_page(dashboard_page_t page)
{
    /* The existing HMI uses the dark PV canvas for battery/system as well. */
    const char *name = touch_page_name(page);
    if (page == DASH_PAGE_BATTERY || page == DASH_PAGE_SYSTEM) name = "pv";
    command("page %s", name);
}

void nextion_render_home(const dashboard_snapshot_t *s, bool live)
{
    char value[64];
    text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    text(18, 55, 134, 20, 2, 2047, 2307, "SOLAR");
    text(175, 55, 134, 20, 2, 2047, 2307, "HOME LOAD");
    text(332, 55, 134, 20, 2, 2047, 2307, "BATTERY");
    text(18, 165, 134, 20, 2, 2047, 2307, "GRID");

    snprintf(value, sizeof(value), "%.0fW", s->pv_total_w);
    text(18, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f+%.0f", s->pv1_w, s->pv2_w);
    text(18, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0fW", s->load_total_w);
    text(175, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f/%.0f/%.0f", s->load_l1_w, s->load_l2_w, s->load_l3_w);
    text(175, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f%%", s->battery_soc);
    text(332, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fV %.0fW", s->battery_voltage_v, s->battery_power_w);
    text(332, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fV", (s->grid_voltage_l1_v + s->grid_voltage_l2_v + s->grid_voltage_l3_v) / 3.0f);
    text(18, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0fW %.0fHz", s->grid_power_w, s->grid_frequency_hz);
    text(18, 226, 134, 26, 2, 65535, 2307, value);
}

void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *s, bool live)
{
    char main[48] = "--";
    char a[72] = "";
    char b[72] = "";
    char c[72] = "";
    const char *title = touch_page_name(page);
    if (page == DASH_PAGE_PV) {
        snprintf(main, sizeof(main), "%.0f W", s->pv_total_w);
        snprintf(a, sizeof(a), "PV1  %.0f W", s->pv1_w);
        snprintf(b, sizeof(b), "PV2  %.0f W", s->pv2_w);
    } else if (page == DASH_PAGE_LOAD) {
        snprintf(main, sizeof(main), "%.0f W", s->load_total_w);
        snprintf(a, sizeof(a), "L1  %.0f W", s->load_l1_w);
        snprintf(b, sizeof(b), "L2  %.0f W", s->load_l2_w);
        snprintf(c, sizeof(c), "L3  %.0f W", s->load_l3_w);
    } else if (page == DASH_PAGE_BATTERY) {
        snprintf(main, sizeof(main), "%.0f%%", s->battery_soc);
        snprintf(a, sizeof(a), "VOLTAGE  %.1f V", s->battery_voltage_v);
        snprintf(b, sizeof(b), "POWER  %.0f W", s->battery_power_w);
    } else if (page == DASH_PAGE_GRID) {
        snprintf(main, sizeof(main), "%.1f V", (s->grid_voltage_l1_v + s->grid_voltage_l2_v + s->grid_voltage_l3_v) / 3.0f);
        snprintf(a, sizeof(a), "L1/L2/L3 %.1f / %.1f / %.1f V", s->grid_voltage_l1_v, s->grid_voltage_l2_v, s->grid_voltage_l3_v);
        snprintf(b, sizeof(b), "EXCHANGE  %.0f W", s->grid_power_w);
        snprintf(c, sizeof(c), "FREQUENCY  %.2f Hz", s->grid_frequency_hz);
    } else if (page == DASH_PAGE_SYSTEM) {
        snprintf(main, sizeof(main), "SYSTEM");
        snprintf(a, sizeof(a), "RASPBERRY HISTORY");
    } else if (page == DASH_PAGE_TODAY) {
        snprintf(main, sizeof(main), "TODAY");
        snprintf(a, sizeof(a), "PV / LOAD HISTORY");
    }
    text(30, 3, 50, 26, 2, 65519, 162, "BACK");
    char upper[16];
    snprintf(upper, sizeof(upper), "%s", title);
    for (char *p = upper; *p; ++p) if (*p >= 'a' && *p <= 'z') *p -= 32;
    text(84, 3, 92, 26, 2, 65535, 162, upper);
    text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    text(18, 52, 145, 26, 3, 65535, 2307, main);
    text(172, 50, 292, 18, 2, 65535, 2307, a);
    text(172, 69, 292, 18, 2, 65535, 2307, b);
    text(18, 85, 446, 16, 2, 65535, 2307, c);
}

static void iso_hhmm(const char *iso, char *output, size_t output_size)
{
    const char *time = iso ? strchr(iso, 'T') : NULL;
    if (time && strlen(time) >= 6) snprintf(output, output_size, "%.5s", time + 1);
    else snprintf(output, output_size, "--:--");
}

static void duration_text(int seconds, char *output, size_t output_size)
{
    if (seconds < 60) snprintf(output, output_size, "%ds", seconds);
    else if (seconds < 3600) snprintf(output, output_size, "%dm", seconds / 60);
    else snprintf(output, output_size, "%dh %02dm", seconds / 3600, (seconds % 3600) / 60);
}

void nextion_render_gaps(const dashboard_gaps_t *gaps, bool live)
{
    char main[32], count[48], longest[48], latest[72];
    char duration[24], start[8], end[8];
    snprintf(main, sizeof(main), "%.1f%%", gaps->coverage_percent);
    snprintf(count, sizeof(count), "GAPS  %d", gaps->gap_count);
    duration_text(gaps->longest_gap_seconds, duration, sizeof(duration));
    snprintf(longest, sizeof(longest), "LONGEST  %s", duration);
    if (gaps->latest_start[0] && gaps->latest_end[0]) {
        iso_hhmm(gaps->latest_start, start, sizeof(start));
        iso_hhmm(gaps->latest_end, end, sizeof(end));
        snprintf(latest, sizeof(latest), "LAST  %s - %s", start, end);
    } else {
        snprintf(latest, sizeof(latest), "NO GAPS");
    }
    text(30, 3, 50, 26, 2, 65519, 162, "BACK");
    text(84, 3, 92, 26, 2, 65535, 162, "GAPS");
    text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    text(18, 52, 145, 26, 3, 65535, 2307, main);
    text(172, 50, 292, 18, 2, 65535, 2307, count);
    text(172, 69, 292, 18, 2, 65535, 2307, longest);
    text(18, 85, 446, 16, 2, 65535, 2307, latest);
}

static float chart_scaled(dashboard_page_t page, size_t channel, float value)
{
    float minimum = 0.0f;
    float maximum = 100.0f;
    if (page == DASH_PAGE_PV || page == DASH_PAGE_LOAD || page == DASH_PAGE_TODAY) maximum = 15000.0f;
    if (page == DASH_PAGE_BATTERY && channel == 1) { minimum = -15000.0f; maximum = 15000.0f; }
    if (page == DASH_PAGE_GRID && channel < 3) { minimum = 180.0f; maximum = 260.0f; }
    if (page == DASH_PAGE_GRID && channel == 3) { minimum = -15000.0f; maximum = 15000.0f; }
    float scaled = (value - minimum) / (maximum - minimum);
    if (scaled < 0) scaled = 0;
    if (scaled > 1) scaled = 1;
    return scaled;
}

void nextion_render_chart(dashboard_page_t page, const dashboard_chart_t *chart)
{
    static const int colors[][4] = {
        [DASH_PAGE_PV] = {65519, 64495, 2047, 0},
        [DASH_PAGE_LOAD] = {65535, 2016, 65519, 2047},
        [DASH_PAGE_BATTERY] = {65519, 64495, 0, 0},
        [DASH_PAGE_GRID] = {65535, 2016, 65519, 64495},
        [DASH_PAGE_SYSTEM] = {2016, 2047, 65519, 64495},
        [DASH_PAGE_TODAY] = {65519, 2047, 0, 0},
        [DASH_PAGE_GAPS] = {2016, 0, 0, 0},
    };
    const int left = 60, top = 120, right = 420, bottom = 240;
    command("fill %d,%d,%d,%d,2307", left, top, right - left + 1, bottom - top + 1);
    for (int x = left; x <= right; x += 72) command("line %d,%d,%d,%d,6597", x, top, x, bottom);
    for (int y = top; y <= bottom; y += 30) command("line %d,%d,%d,%d,6597", left, y, right, y);
    if (!chart || chart->count < 2 || page > DASH_PAGE_GAPS) return;
    for (size_t i = 1; i < chart->count; ++i) {
        int x1 = left + (int)((i - 1) * (right - left) / (chart->count - 1));
        int x2 = left + (int)(i * (right - left) / (chart->count - 1));
        for (size_t channel = 0; channel < chart->channels && channel < 4; ++channel) {
            int y1 = bottom - (int)(chart_scaled(page, channel, chart->samples[i - 1][channel]) * (bottom - top));
            int y2 = bottom - (int)(chart_scaled(page, channel, chart->samples[i][channel]) * (bottom - top));
            command("line %d,%d,%d,%d,%d", x1, y1, x2, y2, colors[page][channel]);
        }
    }
}

bool nextion_read_page_change(dashboard_page_t *page)
{
#if CONFIG_FELICITY_EMULATOR
    return false;
#else
    uint8_t bytes[64];
    int count = uart_read_bytes(PORT, bytes, sizeof(bytes), 0);
    for (int i = 0; i < count; ++i) {
        if (touch_parser_feed(&parser, bytes[i], page)) return true;
    }
    return false;
#endif
}
