#include "nextion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "nextion_protocol.h"

#if CONFIG_FELICITY_EMULATOR
static const char *TAG = "nextion";
#else
static const uart_port_t PORT = UART_NUM_1;
#endif
static touch_parser_t parser;

enum {
    COLOR_HEADER = 162,
    COLOR_LOGO_OUTLINE = 2047,
};

void nextion_command(const char *format, ...)
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

void nextion_text(int x, int y, int w, int h, int font, int color, int background, const char *value)
{
    /* The shipped HMI contains font resources 0.zi and 1.zi only. Older C
     * rendering code used logical sizes 2/3, which makes Nextion reject xstr
     * without drawing text. Match the Python bridge and fall back to font 0. */
    if (font < 0 || font > 1) font = 0;
    nextion_command("xstr %d,%d,%d,%d,%d,%d,%d,1,1,1,\"%s\"", x, y, w, h, font, color, background, value);
}

void nextion_init(void)
{
    touch_parser_reset(&parser);
#if !CONFIG_FELICITY_EMULATOR
    uart_config_t config = {
        /* Start at the Nextion factory default so a power-cycled display can
         * be recovered even if only the volatile `baud` command was used. */
        .baud_rate = 9600,
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

    /* Nextion boots more slowly than the ESP32. `bauds` updates both the
     * active rate and the power-on default; `baud` would be volatile. */
    vTaskDelay(pdMS_TO_TICKS(1000));
    nextion_command("bauds=%d", CONFIG_FELICITY_NEXTION_BAUD);
    ESP_ERROR_CHECK(uart_wait_tx_done(PORT, pdMS_TO_TICKS(250)));
    vTaskDelay(pdMS_TO_TICKS(100));
    ESP_ERROR_CHECK(uart_set_baudrate(PORT, CONFIG_FELICITY_NEXTION_BAUD));
    uart_flush_input(PORT);
    vTaskDelay(pdMS_TO_TICKS(100));

    /* Sending the persistent command again also covers displays that were
     * already configured for the target rate before this boot. */
    nextion_command("bauds=%d", CONFIG_FELICITY_NEXTION_BAUD);
    nextion_command("bkcmd=0");
    nextion_command("sendxy=1");
#endif
}

#if !CONFIG_FELICITY_EMULATOR
static bool uart_wait_byte(uint8_t expected, TickType_t timeout)
{
    TickType_t deadline = xTaskGetTickCount() + timeout;
    uint8_t value = 0;
    while ((int32_t)(deadline - xTaskGetTickCount()) > 0) {
        if (uart_read_bytes(PORT, &value, 1, pdMS_TO_TICKS(50)) == 1 &&
            value == expected) {
            return true;
        }
    }
    return false;
}

static bool uart_read_connect_response(char *response, size_t size,
                                       TickType_t timeout)
{
    if (!response || size < 2) return false;
    TickType_t deadline = xTaskGetTickCount() + timeout;
    size_t used = 0;
    unsigned terminators = 0;
    while ((int32_t)(deadline - xTaskGetTickCount()) > 0 && used + 1 < size) {
        uint8_t value = 0;
        if (uart_read_bytes(PORT, &value, 1, pdMS_TO_TICKS(25)) != 1) continue;
        if (value == 0xff) {
            if (++terminators == 3 && used > 0) {
                response[used] = '\0';
                if (strstr(response, "comok ")) return true;
                used = 0;
                terminators = 0;
            }
            continue;
        }
        terminators = 0;
        response[used++] = (char)value;
    }
    response[used] = '\0';
    return false;
}
#endif

bool nextion_upload_begin(size_t size)
{
#if CONFIG_FELICITY_EMULATOR
    ESP_LOGI(TAG, "NX upload begin: %u bytes", (unsigned)size);
    return true;
#else
    uart_flush_input(PORT);
    static const uint8_t empty[] = {0xff, 0xff, 0xff};
    uart_write_bytes(PORT, empty, sizeof(empty));
    nextion_command("DRAKJHSUYDGBNCJHGJKSHBDN");
    nextion_command("connect");
    static const uint8_t broadcast[] = {0xff, 0xff, 'c', 'o', 'n', 'n', 'e', 'c', 't',
                                        0xff, 0xff, 0xff};
    uart_write_bytes(PORT, broadcast, sizeof(broadcast));
    if (uart_wait_tx_done(PORT, pdMS_TO_TICKS(1000)) != ESP_OK) return false;
    char response[192];
    if (!uart_read_connect_response(response, sizeof(response),
                                    pdMS_TO_TICKS(1000)) ||
        !nextion_connect_model_matches(response, CONFIG_FELICITY_NEXTION_MODEL)) {
        ESP_LOGE("nextion", "Unexpected display response: %s", response);
        return false;
    }
    ESP_LOGI("nextion", "Verified display: %s", CONFIG_FELICITY_NEXTION_MODEL);
    nextion_command("sleep=0");
    nextion_command("whmi-wri %u,%d,0", (unsigned)size,
                    CONFIG_FELICITY_NEXTION_BAUD);
    if (uart_wait_tx_done(PORT, pdMS_TO_TICKS(1000)) != ESP_OK) return false;
    return uart_wait_byte(0x05, pdMS_TO_TICKS(5000));
#endif
}

bool nextion_upload_chunk(const uint8_t *data, size_t size)
{
    if (!data || !size || size > 4096) return false;
#if CONFIG_FELICITY_EMULATOR
    return true;
#else
    int written = uart_write_bytes(PORT, data, size);
    if (written != (int)size ||
        uart_wait_tx_done(PORT, pdMS_TO_TICKS(2000)) != ESP_OK) {
        return false;
    }
    return uart_wait_byte(0x05, pdMS_TO_TICKS(5000));
#endif
}

bool nextion_upload_finish(void)
{
#if CONFIG_FELICITY_EMULATOR
    return true;
#else
    /* Nextion resets after the final acknowledged chunk and emits 0x88 only
     * after its internal flash migration is complete. */
    return uart_wait_byte(0x88, pdMS_TO_TICKS(45000));
#endif
}

void nextion_show_page(dashboard_page_t page)
{
    /* The existing HMI uses the dark PV canvas for battery/system as well. */
    const char *name = touch_page_name(page);
    if (page == DASH_PAGE_BATTERY || page == DASH_PAGE_SYSTEM) name = "pv";
    if (page == DASH_PAGE_SETUP) name = "home";
    nextion_command("page %s", name);
}

static void render_yin_yang(int x)
{
    nextion_command("cirs %d,16,9,65535", x);
    nextion_command("fill %d,7,10,19,%d", x, COLOR_HEADER);
    nextion_command("cirs %d,11,5,%d", x, COLOR_HEADER);
    nextion_command("cirs %d,21,5,65535", x);
    nextion_command("cirs %d,11,1,65535", x);
    nextion_command("cirs %d,21,1,%d", x, COLOR_HEADER);
    nextion_command("cir %d,16,9,%d", x, COLOR_LOGO_OUTLINE);
}

static void render_home_identity(const char *ha_app_version)
{
    nextion_command("fill 0,0,178,32,%d", COLOR_HEADER);
    render_yin_yang(15);
    char version_label[16];
    nextion_format_version_label(ha_app_version, version_label,
                                 sizeof(version_label));
    nextion_text(32, 3, 142, 26, 2, COLOR_LOGO_OUTLINE, COLOR_HEADER,
                 version_label);
}

static void render_detail_identity(void)
{
    nextion_command("fill 0,0,178,32,%d", COLOR_HEADER);
    render_yin_yang(15);
}

void nextion_render_home_values(const dashboard_snapshot_t *s,
                                const dashboard_summary_t *summary, bool live)
{
    char value[64];
    nextion_text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    nextion_text(18, 55, 134, 20, 2, 2047, 2307, "SOLAR");
    nextion_text(175, 55, 134, 20, 2, 2047, 2307, "HOME LOAD");
    nextion_text(332, 55, 134, 20, 2, 2047, 2307, "BATTERY");
    nextion_text(18, 165, 134, 20, 2, 2047, 2307, "GRID");
    nextion_text(175, 165, 134, 20, 2, 2047, 2307, "SYSTEM");
    nextion_text(332, 165, 134, 20, 2, 2047, 2307, "TODAY");

    snprintf(value, sizeof(value), "%.0fW", s->pv_total_w);
    nextion_text(18, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f+%.0f", s->pv1_w, s->pv2_w);
    nextion_text(18, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0fW", s->load_total_w);
    nextion_text(175, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f/%.0f/%.0f", s->load_l1_w, s->load_l2_w, s->load_l3_w);
    nextion_text(175, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f%%", s->battery_soc);
    nextion_text(332, 80, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fV %.0fW", s->battery_voltage_v, s->battery_power_w);
    nextion_text(332, 116, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fV", (s->grid_voltage_l1_v + s->grid_voltage_l2_v + s->grid_voltage_l3_v) / 3.0f);
    nextion_text(18, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0fW %.0fHz", s->grid_power_w, s->grid_frequency_hz);
    nextion_text(18, 226, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.0f%%", summary->cpu_percent);
    nextion_text(175, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "R%.0f T%.0f D%.0f", summary->memory_percent,
             summary->temperature_c, summary->disk_percent);
    nextion_text(175, 226, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fkWh", summary->today_pv_kwh);
    nextion_text(332, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "L%.1f C%.0f%%", summary->today_load_kwh,
             summary->today_coverage_percent);
    nextion_text(332, 226, 134, 26, 2, 65535, 2307, value);
}

void nextion_render_home(const dashboard_snapshot_t *s,
                         const dashboard_summary_t *summary, bool live,
                         const char *ha_app_version)
{
    render_home_identity(ha_app_version);
    nextion_render_home_values(s, summary, live);
}

static void render_detail_header(dashboard_page_t page)
{
    const char *title = touch_page_name(page);
    render_detail_identity();
    nextion_text(30, 3, 50, 26, 2, 65519, 162, "BACK");
    char upper[16];
    snprintf(upper, sizeof(upper), "%s", title);
    for (char *p = upper; *p; ++p) if (*p >= 'a' && *p <= 'z') *p -= 32;
    nextion_text(84, 3, 92, 26, 2, 65535, 162, upper);
    if (page == DASH_PAGE_SYSTEM) {
        nextion_command("draw 374,54,464,97,2016");
        nextion_command("draw 375,55,463,96,2016");
        nextion_text(379, 59, 80, 33, 0, 65535, 2307, "SETUP");
    }
}

static void nextion_system_metric(int y, const char *label, const char *value)
{
    /* Separate right/left-aligned fields keep every decimal value on the same
     * vertical axis instead of centering differently sized complete strings. */
    nextion_command("xstr 172,%d,62,17,0,33840,2307,2,1,1,\"%s\"",
                    y, label);
    nextion_command("xstr 242,%d,116,17,0,65535,2307,0,1,1,\"%s\"",
                    y, value);
}

static void nextion_detail_metric(int y, const char *label, const char *value)
{
    nextion_command("xstr 172,%d,76,17,0,33840,2307,2,1,1,\"%s\"",
                    y, label);
    nextion_command("xstr 256,%d,208,17,0,65535,2307,0,1,1,\"%s\"",
                    y, value);
}

static void nextion_detail_footer(const char *label, const char *value)
{
    nextion_command("xstr 18,85,78,17,0,33840,2307,2,1,1,\"%s\"",
                    label);
    nextion_command("xstr 104,85,360,17,0,65535,2307,0,1,1,\"%s\"",
                    value);
}

void nextion_render_detail_values(dashboard_page_t page,
                                  const dashboard_snapshot_t *s,
                                  const dashboard_summary_t *summary, bool live)
{
    char main[48] = "--";
    char a[72] = "";
    char b[72] = "";
    char c[72] = "";
    const char *label_a = "";
    const char *label_b = "";
    const char *label_c = "";
    if (page == DASH_PAGE_PV) {
        snprintf(main, sizeof(main), "%.0f W", s->pv_total_w);
        label_a = "PV1";
        label_b = "PV2";
        label_c = "MPPT";
        snprintf(a, sizeof(a), "%.0f W", s->pv1_w);
        snprintf(b, sizeof(b), "%.0f W", s->pv2_w);
        snprintf(c, sizeof(c), "%.1f / %.1f V", s->pv_mppt1_v,
                 s->pv_mppt2_v);
    } else if (page == DASH_PAGE_LOAD) {
        snprintf(main, sizeof(main), "%.0f W", s->load_total_w);
        label_a = "L1";
        label_b = "L2";
        label_c = "L3";
        snprintf(a, sizeof(a), "%.0f W", s->load_l1_w);
        snprintf(b, sizeof(b), "%.0f W", s->load_l2_w);
        snprintf(c, sizeof(c), "%.0f W", s->load_l3_w);
    } else if (page == DASH_PAGE_BATTERY) {
        snprintf(main, sizeof(main), "%.0f%%", s->battery_soc);
        label_a = "VOLTAGE";
        label_b = "POWER";
        label_c = "BMS SOC";
        snprintf(a, sizeof(a), "%.1f V / %.1f A", s->battery_voltage_v,
                 s->battery_current_a);
        const char *state = s->battery_power_w > 0 ? "CHARGE" :
                            s->battery_power_w < 0 ? "DISCHARGE" : "IDLE";
        snprintf(b, sizeof(b), "%.0f W / %s", s->battery_power_w, state);
        if (s->battery_bms_count >= 2) {
            snprintf(c, sizeof(c), "%.0f%% / %.0f%%", s->battery_bms1_soc,
                     s->battery_bms2_soc);
        } else if (s->battery_bms_count == 1) {
            snprintf(c, sizeof(c), "%.0f%%", s->battery_bms1_soc);
        } else {
            snprintf(c, sizeof(c), "--");
        }
    } else if (page == DASH_PAGE_GRID) {
        snprintf(main, sizeof(main), "%.1f V", (s->grid_voltage_l1_v + s->grid_voltage_l2_v + s->grid_voltage_l3_v) / 3.0f);
        label_a = "L1/L2/L3";
        label_b = "EXCHANGE";
        label_c = "FREQUENCY";
        snprintf(a, sizeof(a), "%.1f / %.1f / %.1f V", s->grid_voltage_l1_v,
                 s->grid_voltage_l2_v, s->grid_voltage_l3_v);
        snprintf(b, sizeof(b), "%.0f W", s->grid_power_w);
        snprintf(c, sizeof(c), "%.2f Hz", s->grid_frequency_hz);
    } else if (page == DASH_PAGE_SYSTEM) {
        snprintf(main, sizeof(main), "%.1f%% CPU", summary->cpu_percent);
        snprintf(a, sizeof(a), "%.1f%%", summary->memory_percent);
        snprintf(b, sizeof(b), "%.1f C", summary->temperature_c);
        snprintf(c, sizeof(c), "%.1f%%", summary->disk_percent);
    } else if (page == DASH_PAGE_TODAY) {
        snprintf(main, sizeof(main), "PV  %.2f kWh", summary->today_pv_kwh);
        label_a = "LOAD";
        label_b = "COVERAGE";
        label_c = "GRID";
        snprintf(a, sizeof(a), "%.2f kWh", summary->today_load_kwh);
        snprintf(b, sizeof(b), "%.0f%%", summary->today_coverage_percent);
        snprintf(c, sizeof(c), "+%.2f / -%.2f kWh",
                 summary->today_grid_import_kwh, summary->today_grid_export_kwh);
    }
    nextion_text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    if (page == DASH_PAGE_SYSTEM) {
        nextion_text(18, 60, 140, 30, 0, 65535, 2307, main);
        nextion_system_metric(49, "RAM", a);
        nextion_system_metric(67, "TEMP", b);
        nextion_system_metric(85, "DISK", c);
    } else {
        nextion_text(18, 52, 145, 26, 3, 65535, 2307, main);
        nextion_detail_metric(49, label_a, a);
        nextion_detail_metric(67, label_b, b);
        nextion_detail_footer(label_c, c);
    }
}

void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *s,
                           const dashboard_summary_t *summary, bool live)
{
    render_detail_header(page);
    nextion_render_detail_values(page, s, summary, live);
}

void nextion_render_clock(void)
{
    char date[16] = "--.--.----";
    char clock[16] = "--:--:--";
    time_t now = time(NULL);
    struct tm local = {0};
    if (now > 1700000000 && localtime_r(&now, &local)) {
        strftime(date, sizeof(date), "%d.%m.%Y", &local);
        strftime(clock, sizeof(clock), "%H:%M:%S", &local);
    }
    nextion_text(255, 3, 115, 26, 0, 65535, COLOR_HEADER, date);
    nextion_text(375, 3, 98, 26, 0, 65535, COLOR_HEADER, clock);
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

void nextion_render_gaps_values(const dashboard_gaps_t *gaps, bool live)
{
    char main[32], count[48], longest[48], anomaly[72];
    char duration[24], start[8];
    snprintf(main, sizeof(main), "%.1f%%", gaps->coverage_percent);
    snprintf(count, sizeof(count), "%d", gaps->gap_count);
    duration_text(gaps->longest_gap_seconds, duration, sizeof(duration));
    snprintf(longest, sizeof(longest), "%s", duration);
    if (gaps->latest_anomaly_timestamp[0]) {
        iso_hhmm(gaps->latest_anomaly_timestamp, start, sizeof(start));
        snprintf(anomaly, sizeof(anomaly), "%d  LAST %s", gaps->anomaly_count, start);
    } else {
        snprintf(anomaly, sizeof(anomaly), "%d", gaps->anomaly_count);
    }
    nextion_text(180, 3, 70, 26, 2, live ? 2016 : 63488, 162, live ? "LIVE" : "NO DATA");
    nextion_text(18, 52, 145, 26, 3, 65535, 2307, main);
    nextion_detail_metric(49, "GAPS", count);
    nextion_detail_metric(67, "LONGEST", longest);
    /* ANOMALIES is wider than the generic footer's 78 px label column.
     * Give it a dedicated column and preserve an eight-pixel gutter before
     * the value so the label and count never collide on the Nextion. */
    nextion_command("xstr 18,85,96,17,0,33840,2307,2,1,1,\"ANOMALIES\"");
    nextion_command("xstr 122,85,342,17,0,65535,2307,0,1,1,\"%s\"", anomaly);
}

void nextion_render_gaps(const dashboard_gaps_t *gaps, bool live)
{
    render_detail_header(DASH_PAGE_GAPS);
    nextion_render_gaps_values(gaps, live);
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

typedef struct {
    const char *left_top;
    const char *left_middle;
    const char *left_bottom;
    const char *right_top;
    const char *right_middle;
    const char *right_bottom;
} chart_axis_labels_t;

static chart_axis_labels_t chart_axis_labels(dashboard_page_t page)
{
    switch (page) {
        case DASH_PAGE_PV:
        case DASH_PAGE_LOAD:
        case DASH_PAGE_TODAY:
            return (chart_axis_labels_t){"15kW", "7.5k", "0", NULL, NULL, NULL};
        case DASH_PAGE_BATTERY:
            return (chart_axis_labels_t){"100%", "50", "0",
                                         "+15k", "0W", "-15k"};
        case DASH_PAGE_GRID:
            return (chart_axis_labels_t){"260V", "220", "180",
                                         "+15k", "0W", "-15k"};
        case DASH_PAGE_SYSTEM:
            return (chart_axis_labels_t){"100", "50", "0", NULL, NULL, NULL};
        case DASH_PAGE_GAPS:
            return (chart_axis_labels_t){"100%", "50", "0", NULL, NULL, NULL};
        default:
            return (chart_axis_labels_t){"", "", "", NULL, NULL, NULL};
    }
}

static void render_chart_axis_labels(dashboard_page_t page, int top, int bottom)
{
    chart_axis_labels_t labels = chart_axis_labels(page);
    const int middle = (top + bottom) / 2 - 8;
    const int bottom_label = bottom - 16;
    const int positions[] = {top, middle, bottom_label};
    const char *left[] = {labels.left_top, labels.left_middle,
                          labels.left_bottom};
    const char *right[] = {labels.right_top, labels.right_middle,
                           labels.right_bottom};
    for (size_t index = 0; index < 3; ++index) {
        nextion_command("xstr 13,%d,34,16,0,33840,2307,2,1,1,\"%s\"",
                        positions[index], left[index]);
        if (right[index]) {
            nextion_command("xstr 424,%d,43,16,0,33840,2307,0,1,1,\"%s\"",
                            positions[index], right[index]);
        }
    }
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
    /* app_main restores the physical HMI page before every replay. Keep this
     * function to the visible axis/trace commands so samples arrive on screen
     * progressively, like a chart recorder, without accumulating old lines. */
    /* Keep both vertical scales outside the trace rectangle. Battery and Grid
     * use a secondary right-hand scale, while every page retains exactly the
     * same plot geometry and time-axis alignment. */
    const int left = 50, top = 128, right = 421, bottom = 240;
    render_chart_axis_labels(page, top, bottom);
    static const char *day_time[] = {"00:00", "12:00", "24:00"};
    static const char *system_time[] = {"-10m", "-5m", "NOW"};
    const char *const *time_labels = page == DASH_PAGE_SYSTEM
                                         ? system_time
                                         : day_time;
    const int time_x[] = {left, (left + right) / 2 - 26, right - 52};
    for (size_t index = 0; index < 3; ++index) {
        nextion_command("xstr %d,247,52,18,0,33840,2307,0,1,3,\"%s\"",
                        time_x[index], time_labels[index]);
    }
    if (!chart || chart->count < 2 || page > DASH_PAGE_GAPS) return;
    for (size_t i = 1; i < chart->count; ++i) {
        if (!chart->valid[i - 1] || !chart->valid[i]) continue;
        int x1 = left + (int)((i - 1) * (right - left) / (chart->count - 1));
        int x2 = left + (int)(i * (right - left) / (chart->count - 1));
        for (size_t channel = 0; channel < chart->channels && channel < 4; ++channel) {
            int y1 = bottom - (int)(chart_scaled(page, channel, chart->samples[i - 1][channel]) * (bottom - top));
            int y2 = bottom - (int)(chart_scaled(page, channel, chart->samples[i][channel]) * (bottom - top));
            nextion_command("line %d,%d,%d,%d,%d", x1, y1, x2, y2, colors[page][channel]);
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

bool nextion_read_touch(uint16_t *x, uint16_t *y)
{
#if CONFIG_FELICITY_EMULATOR
    (void)x;
    (void)y;
    return false;
#else
    uint8_t byte;
    touch_event_t event;
    while (uart_read_bytes(PORT, &byte, 1, 0) == 1) {
        if (touch_parser_feed_event(&parser, byte, &event) &&
            event.type == TOUCH_EVENT_COORDINATE && !event.pressed) {
            if (x) *x = event.x;
            if (y) *y = event.y;
            return true;
        }
    }
    return false;
#endif
}

bool nextion_read_touch_event(touch_event_t *event)
{
#if CONFIG_FELICITY_EMULATOR
    (void)event;
    return false;
#else
    uint8_t byte;
    touch_event_t parsed;
    while (uart_read_bytes(PORT, &byte, 1, 0) == 1) {
        if (touch_parser_feed_event(&parser, byte, &parsed) &&
            parsed.type == TOUCH_EVENT_COORDINATE) {
            if (event) *event = parsed;
            return true;
        }
    }
    return false;
#endif
}
