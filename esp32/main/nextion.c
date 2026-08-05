#include "nextion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#if CONFIG_FELICITY_NEXTION_TCP_BRIDGE
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <sys/time.h>
#include <unistd.h>
#include "lwip/sockets.h"
#endif

#include "driver/uart.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "nextion";
#if (!CONFIG_FELICITY_EMULATOR || CONFIG_FELICITY_EMULATOR_UART_BRIDGE) && \
    !CONFIG_FELICITY_NEXTION_TCP_BRIDGE
static const uart_port_t PORT = UART_NUM_1;
#endif
static touch_parser_t parser;

#if CONFIG_FELICITY_NEXTION_TCP_BRIDGE
static int tcp_listen_fd = -1;
static int tcp_client_fd = -1;
static bool tcp_connected_event;

static void tcp_close_client(void)
{
    if (tcp_client_fd < 0) return;
    close(tcp_client_fd);
    tcp_client_fd = -1;
    ESP_LOGW(TAG, "Nextion TCP bridge disconnected");
}

static void tcp_accept_client(void)
{
    if (tcp_client_fd >= 0 || tcp_listen_fd < 0) return;
    struct sockaddr_storage address;
    socklen_t address_length = sizeof(address);
    int client = accept(tcp_listen_fd, (struct sockaddr *)&address,
                        &address_length);
    if (client < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            ESP_LOGW(TAG, "Nextion TCP accept failed: errno %d", errno);
        }
        return;
    }
    int enabled = 1;
    struct timeval timeout = {.tv_sec = 5, .tv_usec = 0};
    setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));
    setsockopt(client, SOL_SOCKET, SO_KEEPALIVE, &enabled, sizeof(enabled));
    setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    tcp_client_fd = client;
    tcp_connected_event = true;
    touch_parser_reset(&parser);
    ESP_LOGI(TAG, "Nextion TCP bridge connected");
}

static void tcp_write_bytes(const uint8_t *bytes, size_t length)
{
    tcp_accept_client();
    if (tcp_client_fd < 0) return;
    size_t sent = 0;
    while (sent < length) {
        int result = send(tcp_client_fd, bytes + sent, length - sent, 0);
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) {
            ESP_LOGW(TAG, "Nextion TCP send failed: result %d errno %d",
                     result, errno);
            tcp_close_client();
            return;
        }
        sent += (size_t)result;
    }
}

static void tcp_init(void)
{
    tcp_listen_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    ESP_ERROR_CHECK(tcp_listen_fd < 0 ? ESP_FAIL : ESP_OK);
    int enabled = 1;
    setsockopt(tcp_listen_fd, SOL_SOCKET, SO_REUSEADDR, &enabled,
               sizeof(enabled));
    struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_FELICITY_NEXTION_TCP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    ESP_ERROR_CHECK(bind(tcp_listen_fd, (struct sockaddr *)&address,
                         sizeof(address)) == 0 ? ESP_OK : ESP_FAIL);
    ESP_ERROR_CHECK(listen(tcp_listen_fd, 1) == 0 ? ESP_OK : ESP_FAIL);
    int flags = fcntl(tcp_listen_fd, F_GETFL, 0);
    ESP_ERROR_CHECK(flags < 0 ? ESP_FAIL : ESP_OK);
    ESP_ERROR_CHECK(fcntl(tcp_listen_fd, F_SETFL, flags | O_NONBLOCK) == 0
                        ? ESP_OK : ESP_FAIL);
    ESP_LOGI(TAG, "Waiting for Nextion TCP bridge on port %d",
             CONFIG_FELICITY_NEXTION_TCP_PORT);
}
#endif

#define TEXT_CACHE_SIZE 24
typedef struct {
    int x;
    int y;
    char command[192];
    bool used;
} text_cache_entry_t;
static text_cache_entry_t text_cache[TEXT_CACHE_SIZE];

typedef struct {
    bool active;
    dashboard_page_t page;
    size_t next_sample;
    dashboard_chart_t chart;
} chart_replay_t;
static chart_replay_t chart_replay;

/* Exact plot rectangle from nextion/assets/detail-background.png. */
#define CHART_LEFT 20
#define CHART_TOP 128
#define CHART_RIGHT 452
#define CHART_BOTTOM 247

static void command(const char *format, ...)
{
    char text[192];
    va_list args;
    va_start(args, format);
    vsnprintf(text, sizeof(text), format, args);
    va_end(args);
#if CONFIG_FELICITY_EMULATOR && !CONFIG_FELICITY_EMULATOR_UART_BRIDGE
    ESP_LOGI(TAG, "NX> %s", text);
#elif CONFIG_FELICITY_NEXTION_TCP_BRIDGE
    tcp_write_bytes((const uint8_t *)text, strlen(text));
    static const uint8_t end[] = {0xff, 0xff, 0xff};
    tcp_write_bytes(end, sizeof(end));
#else
    uart_write_bytes(PORT, text, strlen(text));
    static const uint8_t end[] = {0xff, 0xff, 0xff};
    uart_write_bytes(PORT, end, sizeof(end));
#endif
}

static void invalidate_text_cache(void)
{
    memset(text_cache, 0, sizeof(text_cache));
}

static void text_impl(bool cached, int x, int y, int w, int h,
                      int color, int background, int style, const char *value)
{
    char rendered[192];
    /* Match the proven Raspberry bridge command exactly.  The shipped HMI
       contains font 0; referring to fonts 2/3 makes xstr fail on this display. */
    snprintf(rendered, sizeof(rendered),
             "xstr %d,%d,%d,%d,0,%d,%d,0,1,%d,\"%s\"",
             x, y, w, h, color, background, style, value);
    if (cached) {
        text_cache_entry_t *free_entry = NULL;
        for (size_t index = 0; index < TEXT_CACHE_SIZE; ++index) {
            text_cache_entry_t *entry = &text_cache[index];
            if (!entry->used) {
                if (!free_entry) free_entry = entry;
                continue;
            }
            if (entry->x == x && entry->y == y) {
                if (strcmp(entry->command, rendered) == 0) return;
                free_entry = entry;
                break;
            }
        }
        if (free_entry) {
            free_entry->used = true;
            free_entry->x = x;
            free_entry->y = y;
            snprintf(free_entry->command, sizeof(free_entry->command), "%s", rendered);
        }
    }
    command("%s", rendered);
}

static void text(int x, int y, int w, int h, int font, int color, int background, const char *value)
{
    (void)font;
    text_impl(true, x, y, w, h, color, background, 1, value);
}

static void chart_text(int x, int y, int w, int h, int font, int color,
                       int background, const char *value)
{
    /* The chart fill erases its labels, so these must never be suppressed. */
    (void)font;
    text_impl(false, x, y, w, h, color, background, 3, value);
}

static void render_header_identity(void)
{
    command("fill 0,0,178,32,162");
    command("cirs 15,16,9,65535");
    command("fill 15,7,10,19,162");
    command("cirs 15,11,5,162");
    command("cirs 15,21,5,65535");
    command("cirs 15,11,1,65535");
    command("cirs 15,21,1,162");
    command("cir 15,16,9,2047");
}

void nextion_init(void)
{
    touch_parser_reset(&parser);
#if CONFIG_FELICITY_NEXTION_TCP_BRIDGE
    tcp_init();
#elif !CONFIG_FELICITY_EMULATOR || CONFIG_FELICITY_EMULATOR_UART_BRIDGE
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
    command("sleep=0");
    command("thup=1");
    command("ussp=0");
    command("thsp=0");
    command("sendxy=1");
}

void nextion_show_page(dashboard_page_t page)
{
    /* The existing HMI uses the dark PV canvas for battery/system as well. */
    const char *name = touch_page_name(page);
    if (page == DASH_PAGE_BATTERY || page == DASH_PAGE_SYSTEM) name = "pv";
    chart_replay.active = false;
    invalidate_text_cache();
    command("page %s", name);
    /* Let the HMI paint its page bitmap before dynamic text is drawn. */
    vTaskDelay(pdMS_TO_TICKS(80));
    command("sendxy=1");
    render_header_identity();
}

void nextion_render_clock(void)
{
    time_t now;
    struct tm local = {0};
    char date[16] = "--.--.----";
    char clock[16] = "--:--:--";

    time(&now);
    /* An unset ESP clock starts in 1970.  Keep an honest placeholder until
       the first SNTP reply arrives instead of showing a plausible wrong date. */
    if (now >= 1704067200 && localtime_r(&now, &local)) {
        strftime(date, sizeof(date), "%d.%m.%Y", &local);
        strftime(clock, sizeof(clock), "%H:%M:%S", &local);
    }
    /* These are exactly the two header rectangles used by the Raspberry
       bridge.  The text cache means the date is actually sent only once a day. */
    text(255, 3, 115, 26, 0, 65535, 162, date);
    text(375, 3, 98, 26, 0, 65535, 162, clock);
}

static void render_data_state(nextion_data_state_t state)
{
    const char *label = state == NEXTION_DATA_LIVE ? "LIVE" :
                        state == NEXTION_DATA_DEMO ? "DEMO" : "NO DATA";
    uint16_t color = state == NEXTION_DATA_LIVE ? 2016 :
                     state == NEXTION_DATA_DEMO ? 65504 : 63488;
    text(180, 3, 70, 26, 2, color, 162, label);
}

void nextion_render_home(const dashboard_snapshot_t *s, const dashboard_summary_t *summary,
                         nextion_data_state_t state)
{
    char value[64];
    render_data_state(state);
    text(18, 55, 134, 20, 2, 2047, 2307, "SOLAR");
    text(175, 55, 134, 20, 2, 2047, 2307, "HOME LOAD");
    text(332, 55, 134, 20, 2, 2047, 2307, "BATTERY");
    text(18, 165, 134, 20, 2, 2047, 2307, "GRID");
    text(175, 165, 134, 20, 2, 2047, 2307, "SYSTEM");
    text(332, 165, 134, 20, 2, 2047, 2307, "TODAY");

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
    snprintf(value, sizeof(value), "%.0f%%", summary->cpu_percent);
    text(175, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "R%.0f T%.0f D%.0f", summary->memory_percent,
             summary->temperature_c, summary->disk_percent);
    text(175, 226, 134, 26, 2, 65535, 2307, value);
    snprintf(value, sizeof(value), "%.1fkWh", summary->today_pv_kwh);
    text(332, 190, 132, 28, 3, 65535, 2307, value);
    snprintf(value, sizeof(value), "L%.1f C%.0f%%", summary->today_load_kwh,
             summary->today_coverage_percent);
    text(332, 226, 134, 26, 2, 65535, 2307, value);
}

void nextion_render_detail(dashboard_page_t page, const dashboard_snapshot_t *s,
                           const dashboard_summary_t *summary, nextion_data_state_t state)
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
        snprintf(main, sizeof(main), "%.1f%% CPU", summary->cpu_percent);
        snprintf(a, sizeof(a), "RAM  %.1f%%", summary->memory_percent);
        snprintf(b, sizeof(b), "TEMP  %.1f C", summary->temperature_c);
        snprintf(c, sizeof(c), "DISK  %.1f%%", summary->disk_percent);
    } else if (page == DASH_PAGE_TODAY) {
        snprintf(main, sizeof(main), "PV  %.2f kWh", summary->today_pv_kwh);
        snprintf(a, sizeof(a), "LOAD  %.2f kWh", summary->today_load_kwh);
        snprintf(b, sizeof(b), "COVERAGE  %.0f%%", summary->today_coverage_percent);
        snprintf(c, sizeof(c), "GRID +%.2f / -%.2f kWh",
                 summary->today_grid_import_kwh, summary->today_grid_export_kwh);
    }
    text(30, 3, 50, 26, 2, 65519, 162, "BACK");
    char upper[16];
    snprintf(upper, sizeof(upper), "%s", title);
    for (char *p = upper; *p; ++p) if (*p >= 'a' && *p <= 'z') *p -= 32;
    text(84, 3, 92, 26, 2, 65535, 162, upper);
    render_data_state(state);
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

void nextion_render_gaps(const dashboard_gaps_t *gaps, nextion_data_state_t state)
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
    render_data_state(state);
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
    /* The HMI bitmap already owns the canvas, border and grid.  Painting any
       of those from the client creates a visibly foreign rectangle on top of
       the original design.  A page load restores the pristine bitmap; the
       client contributes only labels and data lines. */

    static const char *left_axes[][3] = {
        [DASH_PAGE_PV] = {"15kW", "7.5k", "0"},
        [DASH_PAGE_LOAD] = {"15kW", "7.5k", "0"},
        [DASH_PAGE_BATTERY] = {"100%", "50%", "0%"},
        [DASH_PAGE_GRID] = {"260V", "220V", "180V"},
        [DASH_PAGE_SYSTEM] = {"100", "50", "0"},
        [DASH_PAGE_TODAY] = {"15kW", "7.5k", "0"},
        [DASH_PAGE_GAPS] = {"100%", "50%", "0%"},
    };
    /* Keep the bottom Y labels above the 00:00/12:00/24:00 row. */
    static const int axis_y[] = {111, 174, 225};
    if (page <= DASH_PAGE_GAPS) {
        for (size_t index = 0; index < 3; ++index) {
            chart_text(15, axis_y[index], 42, 14, 0, 31727, 2307,
                       left_axes[page][index]);
        }
    }
    if (page == DASH_PAGE_BATTERY || page == DASH_PAGE_GRID) {
        static const char *right_axis[] = {"+15k", "0", "-15k"};
        for (size_t index = 0; index < 3; ++index) {
            chart_text(424, axis_y[index], 42, 14, 0, 31727, 2307,
                       right_axis[index]);
        }
    }

    if (page == DASH_PAGE_SYSTEM) {
        static const char *system_time[] = {"-10m", "-5m", "NOW"};
        for (size_t index = 0; index < 3; ++index) {
            static const int x[] = {20, 210, 400};
            chart_text(x[index], 247, 52, 14, 0, 31727, 2307, system_time[index]);
        }
    } else {
        static const char *hours[] = {"00:00", "12:00", "24:00"};
        static const int x[] = {20, 210, 400};
        for (size_t index = 0; index < 3; ++index) {
            chart_text(x[index], 247, 52, 14, 0, 31727, 2307, hours[index]);
        }
    }

    chart_replay.active = false;
    if (!chart || chart->count < 2 || page > DASH_PAGE_GAPS) return;
    chart_replay.page = page;
    chart_replay.next_sample = 1;
    chart_replay.chart = *chart;
    chart_replay.active = true;
}

bool nextion_advance_chart(dashboard_page_t current_page, size_t max_samples)
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
    const int left = CHART_LEFT, top = CHART_TOP;
    const int right = CHART_RIGHT, bottom = CHART_BOTTOM;
    if (!chart_replay.active || chart_replay.page != current_page) return false;
    const dashboard_chart_t *chart = &chart_replay.chart;
    size_t stop = chart_replay.next_sample + max_samples;
    if (stop > chart->count) stop = chart->count;
    for (size_t i = chart_replay.next_sample; i < stop; ++i) {
        if (!chart->valid[i - 1] || !chart->valid[i]) continue;
        int x1 = left + (int)((i - 1) * (right - left) / (chart->count - 1));
        int x2 = left + (int)(i * (right - left) / (chart->count - 1));
        for (size_t channel = 0; channel < chart->channels && channel < 4; ++channel) {
            int y1 = bottom - (int)(chart_scaled(current_page, channel,
                                                  chart->samples[i - 1][channel]) * (bottom - top));
            int y2 = bottom - (int)(chart_scaled(current_page, channel,
                                                  chart->samples[i][channel]) * (bottom - top));
            command("line %d,%d,%d,%d,%d", x1, y1, x2, y2,
                    colors[current_page][channel]);
        }
    }
    chart_replay.next_sample = stop;
    if (stop >= chart->count) chart_replay.active = false;
    return chart_replay.active;
}

nextion_event_t nextion_read_event(dashboard_page_t *page)
{
#if CONFIG_FELICITY_EMULATOR && !CONFIG_FELICITY_EMULATOR_UART_BRIDGE
    return NEXTION_EVENT_NONE;
#else
    uint8_t bytes[64];
#if CONFIG_FELICITY_NEXTION_TCP_BRIDGE
    tcp_accept_client();
    if (tcp_connected_event) {
        tcp_connected_event = false;
        return NEXTION_EVENT_DISPLAY_READY;
    }
    if (tcp_client_fd < 0) return NEXTION_EVENT_NONE;
    int count = recv(tcp_client_fd, bytes, sizeof(bytes), MSG_DONTWAIT);
    if (count == 0) {
        tcp_close_client();
        return NEXTION_EVENT_NONE;
    }
    if (count < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) tcp_close_client();
        return NEXTION_EVENT_NONE;
    }
#else
    int count = uart_read_bytes(PORT, bytes, sizeof(bytes), 0);
#endif
    for (int i = 0; i < count; ++i) {
        bool page_changed = touch_parser_feed(&parser, bytes[i], page);
        if (touch_parser_take_display_ready(&parser)) return NEXTION_EVENT_DISPLAY_READY;
        if (page_changed) return NEXTION_EVENT_PAGE_CHANGE;
    }
    return NEXTION_EVENT_NONE;
#endif
}
